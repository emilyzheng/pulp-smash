# coding=utf-8
"""Test groups in comps.xml generated by yum distributor."""
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


def _gen_realistic_group():
    """Return a realistic, typical group unit.

    Most supported fields are filled in on this unit, and there are a few
    translated strings.
    """
    return {
        'id': utils.uuid4(),
        'name': 'Additional Development',
        'translated_name': {'es': 'Desarrollo adicional', 'zh_CN': '附加开发'},
        'description': (
            'Additional development headers and libraries for building '
            'open-source applications'
        ),
        'translated_description': {
            'es': (
                'Encabezados adicionales y bibliotecas para compilar '
                'aplicaciones de código abierto.'
            ),
            'zh_CN': '用于构建开源应用程序的附加开发标头及程序可。',
        },
        'default': True,
        'user_visible': True,
        'display_order': 55,
        'mandatory_package_names': ['PyQt4-devel', 'SDL-devel'],
        'default_package_names': ['perl-devel', 'polkit-devel'],
        'optional_package_names': ['binutils-devel', 'python-devel'],
        'conditional_package_names': [
            ('perl-Test-Pod', 'perl-devel'),
            ('python-setuptools', 'python-devel')
        ],
    }


def _gen_minimal_group():
    """Return a group unit which is as empty as possible.

    This unit omits every non-mandatory field (which, in practice, means that
    it includes only an 'id').
    """
    return {'id': utils.uuid4()}


def _get_groups_by_id(comps_tree):
    """Return each "group" element in ``comps_tree``, keyed by ID.

    :param comps_tree: An ``xml.etree.Element`` instance.
    :returns: A dict in the form ``{id: group_element}``.
    """
    return {
        group.find('id').text: group for group in comps_tree.findall('group')
    }


def _upload_import_package_group(server_config, repo, unit_metadata):
    """Import a unit of type ``package_group`` into a repository.

    :param repo: A dict of attributes about a repository.
    :param unit_metadata: A dict of unit metadata.
    :returns: The call report generated when importing and uploading.
    """
    client = api.Client(server_config, api.json_handler)
    malloc = client.post(CONTENT_UPLOAD_PATH)
    call_report = client.post(
        urljoin(repo['_href'], 'actions/import_upload/'),
        {
            'unit_key': {'id': unit_metadata['id'], 'repo_id': repo['id']},
            'unit_metadata': unit_metadata,
            'unit_type_id': 'package_group',
            'upload_id': malloc['upload_id'],
        },
    )
    client.delete(malloc['_href'])
    return call_report


class CompsGroupsTestCase(utils.BaseAPITestCase):
    """Tests to ensure ``comps.xml`` can be created and groups are valid."""

    @classmethod
    def setUpClass(cls):
        """Create an RPM repository, upload comps metadata, and publish.

        More specifically:

        1. Create a repository.
        2. Add yum distributor to it.
        3. Import fixture group units.
        4. Publish repository.
        5. Fetch and parse generated ``comps.xml``.
        """
        super(CompsGroupsTestCase, cls).setUpClass()

        # Create a repository and add a distributor to it.
        client = api.Client(cls.cfg, api.json_handler)
        repo = client.post(REPOSITORY_PATH, gen_repo())
        cls.resources.add(repo['_href'])
        distributor = client.post(
            urljoin(repo['_href'], 'distributors/'),
            gen_distributor(),
        )

        # Generate several package groups, import them into the repository, and
        # publish the repository.
        #
        # NOTE: The ordering of cls.package_groups matters to test methods! It
        # may be better to make this a dict in the form {label: package_group}.
        cls.package_groups = (_gen_minimal_group(), _gen_realistic_group())
        cls.tasks = {}
        for package_group in cls.package_groups:
            report = _upload_import_package_group(cls.cfg, repo, package_group)
            cls.tasks[package_group['id']] = tuple(
                api.poll_spawned_tasks(cls.cfg, report)
            )
        client.post(
            urljoin(repo['_href'], 'actions/publish/'),
            {'id': distributor['id']},
        )

        # Fetch the generated repodata of type 'group' (a.k.a. 'comps')
        cls.root_element = get_repomd_xml(
            cls.cfg,
            urljoin('/pulp/repos/', distributor['config']['relative_url']),
            'group'
        )

    def test_root(self):
        """Assert the root element of the tree has a tag of "comps"."""
        self.assertEqual(self.root_element.tag, 'comps')

    def test_count(self):
        """Assert there is one "group" element per imported group unit."""
        groups = self.root_element.findall('group')
        self.assertEqual(len(groups), len(self.package_groups))

    def test_ids_alone(self):
        """Assert each "group" element has one "id" child element."""
        for i, group in enumerate(self.root_element.findall('group')):
            with self.subTest(i=i):
                self.assertEqual(len(group.findall('id')), 1)

    def test_ids_unique(self):
        """Assert each group ID is unique."""
        ids = []
        for group in self.root_element.findall('group'):
            for group_id in group.findall('id'):
                ids.append(group_id.text)
        ids.sort()
        deduplicated_ids = list(set(ids))
        deduplicated_ids.sort()
        self.assertEqual(ids, deduplicated_ids)

    def test_one_task_per_import(self):
        """Assert only one task is spawned per package group upload."""
        for group_id, tasks in self.tasks.items():
            with self.subTest(group_id=group_id):
                self.assertEqual(len(tasks), 1)

    def test_tasks_state(self):
        """Assert each task's state is "finished".

        This test assumes :meth:`test_one_task_per_import` passes.
        """
        for group_id, tasks in self.tasks.items():
            with self.subTest(group_id=group_id):
                self.assertEqual(tasks[0]['state'], 'finished')

    def test_tasks_result(self):
        """Assert each task's result success flag (if present) is true.

        This test assumes :meth:`test_one_task_per_import` passes.
        """
        for group_id, tasks in self.tasks.items():
            with self.subTest(group_id=group_id):
                if 'result' not in tasks[0]:
                    continue
                result = tasks[0]['result']
                self.assertTrue(result['success_flag'], result)

    def test_has_groups(self):
        """Assert that each imported group unit appears in the XML."""
        input_ids = {pkg_group['id'] for pkg_group in self.package_groups}
        output_ids = {
            group.find('id').text
            for group in self.root_element.findall('group')
        }
        self.assertEqual(input_ids, output_ids)

    def test_verbatim_string_fields(self):
        """Assert string fields on a unit appear unmodified in generated XML.

        This test covers fields from a group unit which are expected to be
        serialized as-is into top-level tags under a ``<group>``. For example,
        this test asserts that the 'name' attribute on a group unit will appear
        in the generated XML as::

            <group>
                <name>some-value</name>
                ...
            </group>
        """
        input_ = self.package_groups[1]  # realistic package group
        output = _get_groups_by_id(self.root_element)[input_['id']]
        for key in ('id', 'name', 'description', 'display_order'):
            with self.subTest(key=key):
                input_text = type('')(input_[key])
                output_text = output.find(key).text
                self.assertEqual(input_text, output_text)

    def test_verbatim_boolean_fields(self):
        """Assert boolean fields on a unit appear correctly in generated XML.

        This test is similar to :meth:`test_verbatim_string_fields`, but
        additionally verifies that boolean values are serialized as expected in
        the XML (i.e. as text 'true' or 'false').
        """
        input_ = self.package_groups[1]  # realistic package group
        output = _get_groups_by_id(self.root_element)[input_['id']]
        keys_map = (('user_visible', 'uservisible'), ('default', 'default'))
        for input_key, output_key in keys_map:
            with self.subTest(input_key=input_key, output_key=output_key):
                input_value = input_[input_key]
                self.assertIn(input_value, (True, False))
                input_value = type('')(input_value).lower()

                output_value = output.find(output_key).text
                self.assertEqual(input_value, output_value)

    def test_default_display_order(self):
        """Assert display_order is omitted from XML if omitted from unit.

        This test may be skipped if `Pulp #1787
        <https://pulp.plan.io/issues/1787>`_ is open.
        """
        if selectors.bug_is_untestable(1787, self.cfg.version):
            self.skipTest('https://pulp.plan.io/issues/1787')
        input_id = self.package_groups[0]['id']  # minimal package group
        output = _get_groups_by_id(self.root_element)[input_id]
        self.assertEqual(len(output.findall('display_order')), 1)

    def test_single_elements(self):
        """Assert that certain tags appear under groups exactly once."""
        for group in self.root_element.findall('group'):
            for tag in ('default', 'packagelist', 'uservisible'):
                with self.subTest((group.find('id'), tag)):
                    self.assertEqual(len(group.findall(tag)), 1)

    def test_default_default(self):
        """Assert that the default value of ``default`` tag is 'false'."""
        input_id = self.package_groups[0]['id']  # minimal package group
        output = _get_groups_by_id(self.root_element)[input_id]
        self.assertEqual(output.find('default').text, 'false')

    def test_default_uservisible(self):
        """Assert that the default value of ``uservisible`` tag is 'false'."""
        input_id = self.package_groups[0]['id']  # minimal package group
        output = _get_groups_by_id(self.root_element)[input_id]
        self.assertEqual(output.find('uservisible').text, 'false')

    def test_translated_string_count(self):
        """Assert that the XML has correct number of translated strings.

        Some fields (name, description) are translatable. The tags for these
        fields are expected to appear once per translation, plus once for the
        untranslated string. This test verifies that this is the case.
        """
        input_ = self.package_groups[1]  # realistic package group
        output = _get_groups_by_id(self.root_element)[input_['id']]
        for key in ('description', 'name'):
            with self.subTest(key=key):
                input_values = input_['translated_' + key]
                output_values = output.findall(key)
                self.assertEqual(len(input_values) + 1, len(output_values))

    def test_translated_string_values(self):
        """Assert that the XML has correct values for translated strings.

        Some fields (name, description) are translatable. The tags for these
        fields are expected to appear once per translation, plus once for the
        untranslated string. This test verifies that each translated string
        matches exactly the string provided when the group unit was imported.
        """
        input_ = self.package_groups[1]  # realistic package group
        output = _get_groups_by_id(self.root_element)[input_['id']]
        lang_attr = '{http://www.w3.org/XML/1998/namespace}lang'
        for key in ('description', 'name'):
            for value in output.findall(key):
                lang = value.get(lang_attr)
                with self.subTest(key=key, lang=lang):
                    if not lang:
                        continue  # this is the untranslated value
                    input_text = input_['translated_' + key][lang]
                    output_text = value.text
                    self.assertEqual(input_text, output_text)

    def test_packagelist_values(self):
        """Assert packagelist contains packagereq elements with correct text.

        This test verifies that, for each of the 4 possible types of package
        in a group, the packagelist in the group XML contains exactly the
        package names in the uploaded unit.
        """
        input_ = self.package_groups[1]  # realistic package group
        output = _get_groups_by_id(self.root_element)[input_['id']]
        xpath = 'packagelist/packagereq[@type="{}"]'
        for pkg_type in ('mandatory', 'default', 'optional', 'conditional'):
            with self.subTest(pkg_type=pkg_type):
                input_values = input_[pkg_type + '_package_names']
                if pkg_type == 'conditional':
                    # 'conditional' is special: it maps a package name to a
                    # required package. In this test, we only test the package
                    # name part. See test_conditional_requires for testing the
                    # 'requires' attribute.
                    input_values = [key for key, _ in input_values]
                input_values = sorted(input_values)
                output_values = sorted([
                    element.text
                    for element in output.findall(xpath.format(pkg_type))
                ])
                self.assertEqual(input_values, output_values)

    def test_conditional_requires(self):
        """Assert ``requires`` attributes are correct on conditional packages.

        This test assumes :meth:`test_packagelist_values` has passed.
        """
        input_ = self.package_groups[1]  # realistic package group
        output = _get_groups_by_id(self.root_element)[input_['id']]
        xpath = 'packagelist/packagereq[@type="conditional"]'
        conditional_packages_by_name = {
            elem.text: elem for elem in output.findall(xpath)
        }
        for name, requires in input_['conditional_package_names']:
            with self.subTest(name=name):
                conditional_package = conditional_packages_by_name[name]
                self.assertEqual(conditional_package.get('requires'), requires)
