import re
from onecodex.exceptions import ValidationError


def validate_appendables(appendables, api):
    appendables['valid_tags'] = []
    appendables['valid_metadata'] = {'custom': {}}
    validate_tags(appendables, api)
    validate_metadata(appendables, api)
    return appendables


def validate_tags(appendables, api):
    if 'tags' not in appendables:
        return
    tag_array = appendables['tags']
    for tag in tag_array:
        name_property = api.Tags._resource._schema['properties']['name']
        if 'maxLength' in name_property and len(tag) > name_property['maxLength']:
            raise ValidationError('{} is too long'.format(tag))

        appendables['valid_tags'].append({'name': tag})


def validate_metadata(appendables, api):
    if 'metadata' not in appendables:
        return
    schema_props = metadata_properties(api)
    for key, value in appendables['metadata'].items():
        if is_blacklisted(key):
            raise ValidationError('{} cannot be manually updated'.format(key))

        if key in schema_props.keys():
            settable_value = validate_metadata_against_schema(schema_props, key, value)
            appendables['valid_metadata'][key] = settable_value
        else:
            coerced_value = coerce_custom_value(value)
            appendables['valid_metadata']['custom'][key] = coerced_value


def validate_metadata_against_schema(schema_props, key, value):
    schema_rules = schema_props[key]
    if 'enum' in schema_rules:
        return validate_enum(value, schema_rules)
    elif 'number' in schema_rules['type']:
        return validate_number(value, schema_rules)
    elif 'boolean' in schema_rules['type']:
        return validate_boolean(value)
    elif 'format' in schema_rules and 'date-time' in schema_rules['format']:
        return validate_datetime(value)
    else:
        return value


def validate_enum(value, schema_rules):
    if value not in schema_rules['enum']:
        raise ValidationError('{} is not a valid value for this key. Value must be one of the following options: {}'.format(value, schema_rules['enum']))
    return value


def validate_number(value, schema_rules):
    num_value = value
    try:
        num_value = float(value)
    except ValueError:
        raise ValidationError('{} must be a number'.format(value))
    if 'minimum' in schema_rules and num_value <= schema_rules['minimum']:
        raise ValidationError('{} must be larger than the minimum value: {}'.format(value, schema_rules['minimum']))
    if 'maximum' in schema_rules and num_value >= schema_rules['maximum']:
        raise ValidationError('{} must be smaller than the maximum value: {}'.format(value, schema_rules['maximum']))
    return num_value


def validate_boolean(value):
    if value.lower() in truthy_values():
        return True
    elif value.lower() in falsy_values():
        return False
    else:
        raise ValidationError('{} must be either "true" or "false"'.format(value))


def validate_datetime(value):
    if not is_iso_8601_compliant(value):
        raise ValidationError('"{}" must be formatted in iso8601 compliant date format. Example: "2018-05-15T16:21:36+00:00"'.format(value))

    return value


def is_blacklisted(key):
    return key in ['$uri', 'custom']


def truthy_values():
    return ['true', '1', 't', 'y', 'yes']


def falsy_values():
    return ['false', '0', 'f', 'n', 'no']


def coerce_custom_value(value):
    coerced_value = value
    try:
        coerced_value = float(value)
        return coerced_value
    except ValueError:
        pass

    if value.lower() in truthy_values():
        return True

    if value.lower() in falsy_values():
        return False

    return value


def is_iso_8601_compliant(value):
    iso8601 = re.compile(r'^(?P<full>((?P<year>\d{4})([/-]?(?P<mon>(0[1-9])|(1[012]))([/-]?(?P<mday>(0[1-9])|([12]\d)|(3[01])))?)?(?:T(?P<hour>([01][0-9])|(?:2[0123]))(\:?(?P<min>[0-5][0-9])(\:?(?P<sec>[0-5][0-9]([\,\.]\d{1,10})?))?)?(?:Z|([\-+](?:([01][0-9])|(?:2[0123]))(\:?(?:[0-5][0-9]))?))?)?))$')
    return iso8601.match(value)


def metadata_properties(api):
    return api.Metadata._resource._schema['properties']