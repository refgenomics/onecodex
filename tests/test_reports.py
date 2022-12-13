import io
import pytest

import mock
import os
import nbformat

from traitlets.config import Config

import pdfplumber
from onecodex.notebooks.exporters import HTMLExporter, OneCodexPDFExporter


@pytest.fixture
def nb_config():
    config = Config()
    config.OneCodexPDFExporter.preprocessors = ["nbconvert.preprocessors.ExecutePreprocessor"]
    config.HTMLExporter.preprocessors = ["nbconvert.preprocessors.ExecutePreprocessor"]
    yield config


@pytest.fixture
def nb():
    yield nbformat.read("notebook_examples/example.ipynb", as_version=4)


def test_html_report_generation(capsys, nb, nb_config):
    exporter = HTMLExporter(config=nb_config)
    body, resource = exporter.from_notebook_node(nb)

    # Check visualization is generated
    assert "vega-embed" in body
    assert '<div class="vega-visualization"' in body

    # Check no stderr from vega CLI or similar
    assert capsys.readouterr().err == ""


def test_pdf_report_generation(capsys, nb, nb_config):
    exporter = OneCodexPDFExporter(config=nb_config)

    patched_env = os.environ.copy()
    patched_env["ONE_CODEX_DO_NOT_INSERT_DATE"] = "True"

    # do not insert date to prevent from showing up in diff
    with mock.patch.object(os, "environ", patched_env):
        body, _ = exporter.from_notebook_node(nb)

    pdf = pdfplumber.open(io.BytesIO(body))
    page = pdf.pages[0]
    pdf_text = page.extract_text()

    # Check that we have an image (hack is to just check file size)
    assert len(body) > 20000
    assert len(page.images) > 0

    # Check text
    assert "Example Report" in pdf_text
    assert "NOT FOR DIAGNOSTIC USE" in pdf_text

    # Check no stderr from vega CLI or similar
    assert capsys.readouterr().err == ""

    # copy test report to $pwd so that it can be uploaded to github as an
    # artifact
    with open("test-report-generated.pdf", "wb") as handle:
        handle.write(body)
