"""
api.py
author: @mbiokyle29

One Codex API
"""
from __future__ import print_function
from datetime import datetime
import errno
import json
import logging
import os
from requests.auth import HTTPBasicAuth
import warnings

from onecodex.lib.auth import BearerTokenAuth
from onecodex.models import _model_lookup
from onecodex.utils import get_raven_client, collapse_user
from onecodex.vendored.potion_client import Client as PotionClient
from onecodex.vendored.potion_client.converter import PotionJSONSchemaDecoder, PotionJSONDecoder, PotionJSONEncoder
from onecodex.vendored.potion_client.utils import upper_camel_case
from onecodex.version import __version__


log = logging.getLogger(__name__)


class Api(object):
    """
    This is the base One Codex Api object class. It instantiates a Potion-Client
        object under the hood for making requests.
    """

    def __init__(self, api_key=None,
                 bearer_token=None, cache_schema=True,
                 base_url=None, telemetry=None,
                 schema_path='/api/v1/schema'):

        if base_url is None:
            base_url = os.environ.get('ONE_CODEX_API_BASE', 'https://app.onecodex.com')
            if base_url != 'https://app.onecodex.com':
                warnings.warn("Using base API URL: {}".format(base_url))

        self._req_args = {}
        self._base_url = base_url
        self._schema_path = schema_path

        # Attempt to automatically fetch API key from
        # ~/.onecodex file, API key, or bearer token environment vars
        # *if and only if* no auth is explicitly passed to Api
        #
        # TODO: Consider only doing this if an add'l env var like
        #       'ONE_CODEX_AUTO_LOGIN' or similar is set.
        if api_key is None and bearer_token is None:
            creds_file = os.path.expanduser('~/.onecodex')

            if not os.path.exists(creds_file):
                pass
            elif not os.access(creds_file, os.R_OK):
                warnings.warn('Check permissions on {}'.format(collapse_user(creds_file)))
            else:
                try:
                    api_key = json.load(open(creds_file, 'r'))['api_key']
                except KeyError:
                    # lacking an api_key doesn't mean the file is corrupt--it can just be that the
                    # schema was cached after logging in anonymously
                    pass
                except ValueError:
                    warnings.warn('Credentials file ({}) is corrupt'
                                  .format(collapse_user(creds_file)))

            if api_key is None:
                api_key = os.environ.get('ONE_CODEX_API_KEY')
            if bearer_token is None:
                bearer_token = os.environ.get('ONE_CODEX_BEARER_TOKEN')

        if bearer_token:  # prefer bearer token where available
            self._req_args['auth'] = BearerTokenAuth(bearer_token)
        elif api_key:
            self._req_args['auth'] = HTTPBasicAuth(api_key, '')

        self._req_args['headers'] = {'X-OneCodex-Client-User-Agent': __version__}

        # Create client instance
        self._client = ExtendedPotionClient(self._base_url, schema_path=self._schema_path,
                                            fetch_schema=False, **self._req_args)
        self._client._fetch_schema(cache_schema=cache_schema)
        self._session = self._client.session
        self._copy_resources()

        # Optionally configure Raven
        if telemetry is True or (telemetry is None and os.environ.get('ONE_CODEX_AUTO_TELEMETRY', False)):
            self._raven_client = get_raven_client(user_context={'email': self._fetch_account_email()})
            self._telemetry = True
        else:
            self._raven_client = None
            self._telemetry = False

    def _fetch_account_email(self):
        creds_file = os.path.expanduser('~/.onecodex')

        if not os.path.exists(creds_file):
            pass
        elif not os.access(creds_file, os.R_OK):
            warnings.warn('Check permissions on {}'.format(collapse_user(creds_file)))
        else:
            try:
                return json.load(open(creds_file, 'r'))['email']
            except KeyError:
                pass
            except ValueError:
                warnings.warn('Credentials file ({}) is corrupt'.format(collapse_user(creds_file)))

        return os.environ.get('ONE_CODEX_USER_EMAIL', os.environ.get('ONE_CODEX_USER_UUID'))

    def _copy_resources(self):
        """
        Copy all of the resources over to the toplevel client

        -return: populates self with a pointer to each ._client.Resource
        """

        for resource in self._client._resources:
            # set the name param, the keys now have / in them
            potion_resource = self._client._resources[resource]

            try:
                oc_cls = _model_lookup[resource]
                oc_cls._api = self
                oc_cls._resource = potion_resource
                setattr(self, oc_cls.__name__, oc_cls)
            except KeyError:  # Ignore resources we don't explicitly model
                pass


class ExtendedPotionClient(PotionClient):
    """
    An extention of the PotionClient that caches schema
    """
    DATE_FORMAT = "%Y-%m-%d %H:%M"
    SCHEMA_SAVE_DURATION = 1  # day

    def fetch(self, uri, cls=PotionJSONDecoder, **kwargs):
        if uri in self._cached_schema:
            return self._cached_schema[uri]
        return super(ExtendedPotionClient, self).fetch(uri, cls=cls, **kwargs)

    def _fetch_schema(self, cache_schema=True, creds_file=None):
        self._cached_schema = {}

        creds_file = os.path.expanduser('~/.onecodex') if creds_file is None else creds_file
        creds = {}

        if not os.path.exists(creds_file):
            pass
        elif not os.access(creds_file, os.R_OK):
            warnings.warn('Check permissions on {}'.format(collapse_user(creds_file)))
        else:
            try:
                creds = json.load(open(creds_file, 'r'))
            except ValueError:
                warnings.warn('Credentials file ({}) is corrupt'.format(collapse_user(creds_file)))

        serialized_schema = None

        if cache_schema:
            # determine if we need to update
            schema_update_needed = True
            last_update = creds.get('schema_saved_at')

            if last_update is not None:
                last_update = datetime.strptime(last_update, self.DATE_FORMAT)
                time_diff = datetime.now() - last_update
                schema_update_needed = time_diff.days > self.SCHEMA_SAVE_DURATION

            if not schema_update_needed:
                # get the schema from the credentials file (as a string)
                serialized_schema = creds.get('schema')

        if serialized_schema is None:
            # if the schema wasn't cached or if it was expired, get it anew
            schema = self.session.get(self._schema_url).json(cls=PotionJSONSchemaDecoder,
                                                             referrer=self._schema_url,
                                                             client=self)

            expanded_schema = self.session.get(self._schema_url + '?expand=all').json()

            # serialize the main schema
            serialized_schema = {}
            serialized_schema[self._schema_url] = json.dumps(schema, cls=PotionJSONEncoder)

            # serialize the object schemas
            for schema_name, schema_ref in schema['properties'].items():
                cur_schema = expanded_schema['properties'][schema_name]
                serialized_schema[schema_ref._uri] = json.dumps(
                    cur_schema, cls=PotionJSONEncoder
                )

        # save schema if we're going to, otherwise delete it from creds file
        if cache_schema:
            creds['schema_saved_at'] = datetime.strftime(datetime.now(), self.DATE_FORMAT)
            creds['schema'] = serialized_schema
        else:
            if 'schema_saved_at' in creds:
                del creds['schema_saved_at']
            if 'schema' in creds:
                del creds['schema']

        # always resave the creds (to make sure we're removing or saving the cached schema)
        try:
            if creds:
                json.dump(creds, open(creds_file, 'w'))
            else:
                os.remove(creds_file)
        except Exception as e:
            if e.errno == errno.ENOENT:
                pass
            elif e.errno == errno.EACCES:
                warnings.warn('Check permissions on {}'.format(collapse_user(creds_file)))
            else:
                raise

        # by the time we get here, we should have loaded the serialized schema from creds_file or
        # pulled it from the API and serialized it. now, we unserialize it and put it where it
        # needs to be.
        base_schema = serialized_schema.pop(self._schema_url, None)
        base_schema = json.loads(base_schema, cls=PotionJSONSchemaDecoder,
                                 referrer=self._schema_url, client=self)

        for name, schema_ref in base_schema['properties'].items():
            object_schema = json.loads(
                serialized_schema[schema_ref._uri],
                cls=PotionJSONSchemaDecoder,
                referrer=self._schema_url,
                client=self
            )

            object_schema['_base_uri'] = schema_ref._uri.replace('/schema#', '')

            self._cached_schema[schema_ref._uri] = object_schema

            class_name = upper_camel_case(name)
            setattr(self, class_name, self.resource_factory(name, object_schema))
