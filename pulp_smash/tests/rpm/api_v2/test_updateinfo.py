# coding=utf-8
"""Test updateinfo XML generated by yum distributor."""
from __future__ import unicode_literals

from pulp_smash import api, selectors, utils
from pulp_smash.compat import urljoin
from pulp_smash.constants import CONTENT_UPLOAD_PATH, REPOSITORY_PATH
from pulp_smash.tests.rpm.api_v2.utils import (
    gen_distributor,
    gen_repo,
    get_repomd_xml,
)
from pulp_smash.tests.rpm.utils import set_up_module as setUpModule  # noqa pylint:disable=unused-import


def _gen_errata_typical():
    """Generate and return a typical erratum with a unique ID."""
    return {
        'id': utils.uuid4(),
        'description': (
            'This sample description contains some non-ASCII characters '
            ', such as: 汉堡™, and also contains a long line which some '
            'systems may be tempted to wrap.  It will be tested to see '
            'if the string survives a round-trip through the API and '
            'back out of the yum distributor as XML without any '
            'modification.'
        ),
        'issued': '2015-03-05 05:42:53 UTC',
        'pkglist': [{
            'name': 'pkglist-name',
            'packages': [{
                'arch': 'i686',
                'epoch': '0',
                'filename': 'libpfm-4.4.0-9.el7.i686.rpm',
                'name': 'libpfm',
                'release': '9.el7',
                'src': 'libpfm-4.4.0-9.el7.src.rpm',
                'sum': [
                    'sha256',
                    ('ca42a0d97fd99a195b30f9256823a46c94f632c126ab4fbbdd7e1276'
                     '41f30ee4')
                ],
                'version': '4.4.0',
            }],
        }],
        'references': [{
            'href': 'https://example.com/errata/PULP-2017-1234.html',
            'id': 'PULP-2017:1234',
            'title': 'PULP-2017:1234',
            'type': 'self'
        }],
        'solution': 'sample solution',
        'status': 'final',
        'title': 'sample title',
        'type': 'pulp',
        'version': '6',  # intentionally string, not int
    }


def _gen_errata_no_pkglist():
    """Generate and return an erratum with no package list and a unique ID."""
    return {
        'description': 'this unit has no packages',
        'id': utils.uuid4(),
        'issued': '2015-04-05 05:42:53 UTC',
        'solution': 'solution for no pkglist',
        'status': 'final',
        'title': 'no pkglist',
        'type': 'PULP',
        'version': '9',
    }


def _get_updates_by_id(update_info_tree):
    """Return each "update" element in ``update_info_tree``, keyed by ID.

    :param update_info_tree: An ``Element``.
    :returns: A dict in the form ``{id, update_element}``.
    """
    return {
        update.findall('id')[0].text: update
        for update in update_info_tree.findall('update')
    }


def _upload_import_erratum(server_config, erratum, repo_href):
    """Upload an erratum to a Pulp server and import it into a repository.

    Create an upload request, upload ``erratum`` (after wrapping it), import it
    into the repository at ``repo_href``, and close the upload request. Return
    the call report received when importing the erratum.
    """
    client = api.Client(server_config, api.json_handler)
    malloc = client.post(CONTENT_UPLOAD_PATH)
    call_report = client.post(urljoin(repo_href, 'actions/import_upload/'), {
        'unit_key': {'id': erratum['id']},
        'unit_metadata': erratum,
        'unit_type_id': 'erratum',
        'upload_id': malloc['upload_id'],
    })
    client.delete(malloc['_href'])
    return call_report


class UpdateInfoTestCase(utils.BaseAPITestCase):
    """Tests to ensure ``updateinfo.xml`` can be created and is valid."""

    @classmethod
    def setUpClass(cls):
        """Create an RPM repository, upload errata, and publish the repository.

        More specifically, do the following:

        1. Create an RPM repository.
        2. Add a YUM distributor.
        3. Generate a pair of errata. Upload them to Pulp and import them into
           the repository.
        4. Publish the repository. Fetch the ``updateinfo.xml`` file from the
           distributor (via ``repomd.xml``), and parse it.
        """
        super(UpdateInfoTestCase, cls).setUpClass()
        cls.errata = {
            'import_no_pkglist': _gen_errata_no_pkglist(),
            'import_typical': _gen_errata_typical(),
        }
        cls.tasks = {}  # {'import_no_pkglist': (…), 'import_typical': (…)}

        # Create a repository and add a yum distributor.
        client = api.Client(cls.cfg, api.json_handler)
        repo = client.post(REPOSITORY_PATH, gen_repo())
        cls.resources.add(repo['_href'])
        distributor = client.post(
            urljoin(repo['_href'], 'distributors/'),
            gen_distributor(),
        )

        # Import errata into our repository. Publish the repository.
        for key, erratum in cls.errata.items():
            report = _upload_import_erratum(cls.cfg, erratum, repo['_href'])
            cls.tasks[key] = tuple(api.poll_spawned_tasks(cls.cfg, report))
        client.post(
            urljoin(repo['_href'], 'actions/publish/'),
            {'id': distributor['id']},
        )

        # Fetch and parse updateinfo.xml (or updateinfo.xml.gz), via repomd.xml
        cls.root_element = get_repomd_xml(
            cls.cfg,
            urljoin('/pulp/repos/', distributor['config']['relative_url']),
            'updateinfo'
        )

    def test_root(self):
        """Assert the root element of the tree has a tag of "updates"."""
        self.assertEqual(self.root_element.tag, 'updates')

    def test_one_update_per_errata(self):
        """Assert there is one "update" element per importer erratum."""
        update_elements = self.root_element.findall('update')
        self.assertEqual(len(update_elements), len(self.errata))

    def test_update_ids_alone(self):
        """Assert each "update" element has one "id" child element.

        Each "update" element has an "id" child element. Each parent should
        have exactly one of these children.
        """
        for update_element in self.root_element.findall('update'):
            with self.subTest(update_element=update_element):
                self.assertEqual(len(update_element.findall('id')), 1)

    def test_update_ids_unique(self):
        """Assert each update ID is unique.

        Each "update" element has an "id" child element. These IDs should be
        unique.
        """
        update_ids = set()
        for update_element in self.root_element.findall('update'):
            for id_element in update_element.findall('id'):
                update_id = id_element.text
                with self.subTest(update_id=update_id):
                    self.assertNotIn(update_id, update_ids)
                    update_ids.add(update_id)

    def test_one_task_per_import(self):
        """Assert only one task is spawned per erratum upload."""
        for key, tasks in self.tasks.items():
            with self.subTest(key=key):
                self.assertEqual(len(tasks), 1)

    def test_tasks_state(self):
        """Assert each task's state is "finished".

        This test assumes :meth:`test_one_task_per_import` passes.
        """
        for key, tasks in self.tasks.items():
            with self.subTest(key=key):
                self.assertEqual(tasks[0]['state'], 'finished')

    def test_tasks_result(self):
        """Assert each task's result success flag (if present) is true.

        This test assumes :meth:`test_one_task_per_import` passes.
        """
        for key, tasks in self.tasks.items():
            with self.subTest(key=key):
                if 'result' not in tasks[0]:
                    continue
                result = tasks[0]['result']
                self.assertTrue(result['success_flag'], result)

    def test_erratum_description(self):
        """Assert the update info tree has a correct erratum description.

        This test case uploads an erratum that has an interesting description
        with non-ASCII characters, long lines, etc. The erratum description is
        later made available in the update info tree. Verify the description is
        unchanged.
        """
        erratum = self.errata['import_typical']
        update_element = _get_updates_by_id(self.root_element)[erratum['id']]
        description_elements = update_element.findall('description')
        self.assertEqual(len(description_elements), 1, description_elements)
        self.assertEqual(description_elements[0].text, erratum['description'])

    def test_reboot_not_suggested(self):
        """Assert the update info tree does not suggest a spurious reboot.

        The ``import_typical`` erratum does not suggest that a reboot be
        applied. As a result, the relevant "update" element in the update info
        tree should not suggest that a reboot be applied (via a
        ``reboot_suggested`` element). Verify that this is so.

        This test may be skipped if `Pulp #1782
        <https://pulp.plan.io/issues/1782>`_ is open.
        """
        if selectors.bug_is_untestable(1782, self.cfg.version):
            self.skipTest('https://pulp.plan.io/issues/1782')
        erratum_id = self.errata['import_typical']['id']
        update_element = _get_updates_by_id(self.root_element)[erratum_id]
        reboot_elements = update_element.findall('reboot_suggested')
        self.assertEqual(len(reboot_elements), 1, reboot_elements)
