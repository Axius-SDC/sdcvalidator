#!/usr/bin/env python
#
# Copyright (c), 2016-2020, SISSA (International School for Advanced Studies).
# All rights reserved.
# This file is distributed under the terms of the MIT License.
# See the file 'LICENSE' in the root directory of the present
# distribution, or http://opensource.org/licenses/MIT.
#
# @author Davide Brunato <brunato@sissa.it>
#
"""Tests concerning XML resources"""

import unittest
import os
import platform
import warnings
from io import StringIO
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import urlsplit, uses_relative
from pathlib import Path, PureWindowsPath, PurePath
from xml.etree import ElementTree

try:
    import lxml.etree as lxml_etree
except ImportError:
    lxml_etree = None

from xmlschema import (
    fetch_namespaces, fetch_resource, normalize_url, fetch_schema, fetch_schema_locations,
    XMLResource, XMLResourceError, XMLSchema, XMLSchema10, XMLSchema11
)
from xmlschema.etree import etree_element, py_etree_element, is_etree_element
from xmlschema.namespaces import XSD_NAMESPACE
from xmlschema.resources import is_url, is_local_url, is_remote_url, \
    url_path_is_file, update_prefix, normalize_locations
from xmlschema.documents import get_context
from xmlschema.testing import SKIP_REMOTE_TESTS


TEST_CASES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_cases/')


def casepath(relative_path):
    return os.path.join(TEST_CASES_DIR, relative_path)


def is_windows_path(path):
    """Checks if the path argument is a Windows platform path."""
    return '\\' in path or ':' in path or '|' in path


def add_leading_slash(path):
    return '/' + path if path and path[0] not in ('/', '\\') else path


def filter_windows_path(path):
    if path.startswith('/\\'):
        return path[1:]
    elif path and path[0] not in ('/', '\\'):
        return '/' + path
    else:
        return path


class TestResources(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.schema_class = XMLSchema10
        cls.vh_dir = casepath('examples/vehicles')
        cls.vh_xsd_file = casepath('examples/vehicles/vehicles.xsd')
        cls.vh_xml_file = casepath('examples/vehicles/vehicles.xml')

        cls.col_dir = casepath('examples/collection')
        cls.col_xsd_file = casepath('examples/collection/collection.xsd')
        cls.col_xml_file = casepath('examples/collection/collection.xml')

    def check_url(self, url, expected):
        url_parts = urlsplit(url)
        if urlsplit(expected).scheme not in uses_relative:
            expected = add_leading_slash(expected)

        expected_parts = urlsplit(expected, scheme='file')

        self.assertEqual(url_parts.scheme, expected_parts.scheme,
                         "%r: Schemes differ." % url)
        self.assertEqual(url_parts.netloc, expected_parts.netloc,
                         "%r: Netloc parts differ." % url)
        self.assertEqual(url_parts.query, expected_parts.query,
                         "%r: Query parts differ." % url)
        self.assertEqual(url_parts.fragment, expected_parts.fragment,
                         "%r: Fragment parts differ." % url)

        if is_windows_path(url_parts.path) or is_windows_path(expected_parts.path):
            path = PureWindowsPath(filter_windows_path(url_parts.path))
            expected_path = PureWindowsPath(filter_windows_path(expected_parts.path))
        else:
            path = PurePath(url_parts.path)
            expected_path = PurePath(expected_parts.path)
        self.assertEqual(path, expected_path, "%r: Paths differ." % url)

    def test_normalize_url_posix(self):
        url1 = "https://example.com/xsd/other_schema.xsd"
        self.check_url(normalize_url(url1, base_url="/path_my_schema/schema.xsd"), url1)

        parent_dir = os.path.dirname(os.getcwd())
        self.check_url(normalize_url('../dir1/./dir2'), os.path.join(parent_dir, 'dir1/dir2'))
        self.check_url(normalize_url('../dir1/./dir2', '/home', keep_relative=True),
                       'file:///dir1/dir2')
        self.check_url(normalize_url('../dir1/./dir2', 'file:///home'), 'file:///dir1/dir2')

        self.check_url(normalize_url('other.xsd', 'file:///home'), 'file:///home/other.xsd')
        self.check_url(normalize_url('other.xsd', 'file:///home/'), 'file:///home/other.xsd')
        self.check_url(normalize_url('file:other.xsd', 'file:///home'), 'file:///home/other.xsd')

        cwd = os.getcwd()
        cwd_url = 'file://{}/'.format(cwd) if cwd.startswith('/') else 'file:///{}/'.format(cwd)

        self.check_url(normalize_url('file:other.xsd', keep_relative=True), 'file:other.xsd')
        self.check_url(normalize_url('file:other.xsd'), cwd_url + 'other.xsd')
        self.check_url(normalize_url('file:other.xsd', 'http://site/base', True), 'file:other.xsd')
        self.check_url(normalize_url('file:other.xsd', 'http://site/base'), cwd_url + 'other.xsd')

        self.check_url(normalize_url('dummy path.xsd'), cwd_url + 'dummy path.xsd')
        self.check_url(normalize_url('dummy path.xsd', 'http://site/base'),
                       'http://site/base/dummy%20path.xsd')
        self.check_url(normalize_url('dummy path.xsd', 'file://host/home/'),
                       'file://host/home/dummy path.xsd')

    def test_normalize_url_windows(self):
        win_abs_path1 = 'z:\\Dir_1_0\\Dir2-0\\schemas/XSD_1.0/XMLSchema.xsd'
        win_abs_path2 = 'z:\\Dir-1.0\\Dir-2_0\\'
        self.check_url(normalize_url(win_abs_path1), win_abs_path1)

        self.check_url(normalize_url('k:\\Dir3\\schema.xsd', win_abs_path1),
                       'file:///k:\\Dir3\\schema.xsd')
        self.check_url(normalize_url('k:\\Dir3\\schema.xsd', win_abs_path2),
                       'file:///k:\\Dir3\\schema.xsd')
        self.check_url(normalize_url('schema.xsd', win_abs_path2),
                       'file:///z:\\Dir-1.0\\Dir-2_0/schema.xsd')
        self.check_url(normalize_url('xsd1.0/schema.xsd', win_abs_path2),
                       'file:///z:\\Dir-1.0\\Dir-2_0/xsd1.0/schema.xsd')
        self.check_url(normalize_url('file:///\\k:\\Dir A\\schema.xsd'),
                       'file:///k:\\Dir A\\schema.xsd')

    def test_normalize_url_slashes(self):
        # Issue #116
        self.assertEqual(
            normalize_url('//anaconda/envs/testenv/lib/python3.6/'
                          'site-packages/xmlschema/validators/schemas/'),
            'file:///anaconda/envs/testenv/lib/python3.6/'
            'site-packages/xmlschema/validators/schemas/'
        )
        self.assertEqual(normalize_url('/root/dir1/schema.xsd'), 'file:///root/dir1/schema.xsd')
        self.assertEqual(normalize_url('//root/dir1/schema.xsd'), 'file:///root/dir1/schema.xsd')
        self.assertEqual(normalize_url('////root/dir1/schema.xsd'), 'file:///root/dir1/schema.xsd')

        self.assertEqual(normalize_url('dir2/schema.xsd', '//root/dir1/'),
                         'file:///root/dir1/dir2/schema.xsd')
        self.assertEqual(normalize_url('dir2/schema.xsd', '//root/dir1'),
                         'file:///root/dir1/dir2/schema.xsd')
        self.assertEqual(normalize_url('dir2/schema.xsd', '////root/dir1'),
                         'file:///root/dir1/dir2/schema.xsd')

    def test_normalize_url_hash_character(self):
        self.check_url(normalize_url('issue #000.xml', 'file:///dir1/dir2/'),
                       'file:///dir1/dir2/issue %23000.xml')
        self.check_url(normalize_url('data.xml', 'file:///dir1/dir2/issue 000'),
                       'file:///dir1/dir2/issue 000/data.xml')
        self.check_url(normalize_url('data.xml', '/dir1/dir2/issue #000'),
                       '/dir1/dir2/issue %23000/data.xml')

    def test_is_url_function(self):
        self.assertTrue(is_url(self.col_xsd_file))
        self.assertFalse(is_url('http://example.com['))
        self.assertFalse(is_url(' \t<root/>'))
        self.assertFalse(is_url('line1\nline2'))
        self.assertFalse(is_url(None))

    def test_is_local_url_function(self):
        self.assertTrue(is_local_url(self.col_xsd_file))
        self.assertTrue(is_local_url('/home/user/'))
        self.assertTrue(is_local_url('/home/user/schema.xsd'))
        self.assertTrue(is_local_url('  /home/user/schema.xsd  '))
        self.assertTrue(is_local_url('C:\\Users\\foo\\schema.xsd'))
        self.assertTrue(is_local_url(' file:///home/user/schema.xsd'))
        self.assertFalse(is_local_url('http://example.com/schema.xsd'))

    def test_is_remote_url_function(self):
        self.assertFalse(is_remote_url(self.col_xsd_file))
        self.assertFalse(is_remote_url('/home/user/'))
        self.assertFalse(is_remote_url('/home/user/schema.xsd'))
        self.assertFalse(is_remote_url(' file:///home/user/schema.xsd'))
        self.assertTrue(is_remote_url('  http://example.com/schema.xsd'))

    def test_url_path_is_file_function(self):
        self.assertTrue(url_path_is_file(self.col_xml_file))
        self.assertFalse(url_path_is_file(self.col_dir))
        self.assertFalse(url_path_is_file('http://example.com/'))

    def test_update_prefix_function(self):
        nsmap = {}
        update_prefix(nsmap, 'xs', XSD_NAMESPACE)
        self.assertEqual(nsmap, {'xs': XSD_NAMESPACE})
        update_prefix(nsmap, 'xs', XSD_NAMESPACE)
        self.assertEqual(nsmap, {'xs': XSD_NAMESPACE})
        update_prefix(nsmap, 'tns0', 'http://example.com/ns')
        self.assertEqual(nsmap, {'xs': XSD_NAMESPACE, 'tns0': 'http://example.com/ns'})
        update_prefix(nsmap, 'xs', 'http://example.com/ns')
        self.assertEqual(nsmap, {'xs': XSD_NAMESPACE,
                                 'xs0': 'http://example.com/ns',
                                 'tns0': 'http://example.com/ns'})
        update_prefix(nsmap, 'xs', 'http://example.com/ns')
        self.assertEqual(nsmap, {'xs': XSD_NAMESPACE,
                                 'xs0': 'http://example.com/ns',
                                 'tns0': 'http://example.com/ns'})

        update_prefix(nsmap, 'xs', 'http://example.com/ns2')
        self.assertEqual(nsmap, {'xs': XSD_NAMESPACE,
                                 'xs0': 'http://example.com/ns',
                                 'xs1': 'http://example.com/ns2',
                                 'tns0': 'http://example.com/ns'})

    def test_normalize_locations_function(self):
        locations = normalize_locations(
            [('tns0', 'alpha'), ('tns1', 'http://example.com/beta')], base_url='/home/user'
        )
        self.assertListEqual(locations, [('tns0', 'file:///home/user/alpha'),
                                         ('tns1', 'http://example.com/beta')])

        locations = normalize_locations(
            {'tns0': 'alpha', 'tns1': 'http://example.com/beta'}, base_url='/home/user'
        )
        self.assertListEqual(locations, [('tns0', 'file:///home/user/alpha'),
                                         ('tns1', 'http://example.com/beta')])

        locations = normalize_locations(
            {'tns0': ['alpha', 'beta'], 'tns1': 'http://example.com/beta'}, base_url='/home/user'
        )
        self.assertListEqual(locations, [('tns0', 'file:///home/user/alpha'),
                                         ('tns0', 'file:///home/user/beta'),
                                         ('tns1', 'http://example.com/beta')])

        locations = normalize_locations(
            {'tns0': 'alpha', 'tns1': 'http://example.com/beta'}, keep_relative=True
        )
        self.assertListEqual(locations, [('tns0', 'file:alpha'),
                                         ('tns1', 'http://example.com/beta')])

    def test_fetch_resource_function(self):
        with self.assertRaises(ValueError) as ctx:
            fetch_resource('')
        self.assertIn('argument must contain a not empty string', str(ctx.exception))

        wrong_path = casepath('resources/dummy_file.txt')
        self.assertRaises(XMLResourceError, fetch_resource, wrong_path)

        wrong_path = casepath('/home/dummy_file.txt')
        self.assertRaises(XMLResourceError, fetch_resource, wrong_path)

        right_path = casepath('resources/dummy file.txt')
        self.assertTrue(fetch_resource(right_path).endswith('dummy file.txt'))

        right_path = Path(casepath('resources/dummy file.txt')).relative_to(os.getcwd())
        self.assertTrue(fetch_resource(str(right_path), '/home').endswith('dummy file.txt'))

        with self.assertRaises(XMLResourceError):
            fetch_resource(str(right_path.parent.joinpath('dummy_file.txt')), '/home')

        ambiguous_path = casepath('resources/dummy file #2.txt')
        self.assertTrue(fetch_resource(ambiguous_path).endswith('dummy file %232.txt'))

        with urlopen(fetch_resource(ambiguous_path)) as res:
            self.assertEqual(res.read(), b'DUMMY CONTENT')

    def test_fetch_namespaces_function(self):
        self.assertFalse(fetch_namespaces(casepath('resources/malformed.xml')))

    def test_fetch_schema_locations(self):
        locations = fetch_schema_locations(self.col_xml_file)
        self.check_url(locations[0], self.col_xsd_file)
        self.assertEqual(locations[1][0][0], 'http://example.com/ns/collection')
        self.check_url(locations[1][0][1], self.col_xsd_file)
        self.check_url(fetch_schema(self.vh_xml_file), self.vh_xsd_file)

        with self.assertRaises(ValueError) as ctx:
            fetch_schema_locations('<empty/>')
        self.assertIn('does not contain any schema location hint', str(ctx.exception))

    def test_get_context(self):
        source, schema = get_context(self.col_xml_file)
        self.assertIsInstance(source, XMLResource)
        self.assertIsInstance(schema, XMLSchema)

        source, schema = get_context(self.col_xml_file, self.col_xsd_file)
        self.assertIsInstance(source, XMLResource)
        self.assertIsInstance(schema, XMLSchema)

        source, schema = get_context(self.vh_xml_file, cls=XMLSchema10)
        self.assertIsInstance(source, XMLResource)
        self.assertIsInstance(schema, XMLSchema10)

        source, schema = get_context(self.col_xml_file, cls=XMLSchema11)
        self.assertIsInstance(source, XMLResource)
        self.assertIsInstance(schema, XMLSchema11)

        source, schema = get_context(XMLResource(self.vh_xml_file))
        self.assertIsInstance(source, XMLResource)
        self.assertIsInstance(schema, XMLSchema)

        # Issue #145
        with open(self.vh_xml_file) as f:
            source, schema = get_context(f, schema=self.vh_xsd_file)
            self.assertIsInstance(source, XMLResource)
            self.assertIsInstance(schema, XMLSchema)

        with open(self.vh_xml_file) as f:
            source, schema = get_context(XMLResource(f), schema=self.vh_xsd_file)
            self.assertIsInstance(source, XMLResource)
            self.assertIsInstance(schema, XMLSchema)

        with open(self.vh_xml_file) as f:
            source, schema = get_context(f, base_url=self.vh_dir)
            self.assertIsInstance(source, XMLResource)
            self.assertIsInstance(schema, XMLSchema)

    # Tests on XMLResource instances
    def test_xml_resource_representation(self):
        resource = XMLResource(self.vh_xml_file)
        self.assertTrue(str(resource).startswith(
            "XMLResource(root=<Element '{http://example.com/vehicles}vehicles'"
        ))

    def test_xml_resource_from_url(self):
        resource = XMLResource(self.vh_xml_file, lazy=True)
        self.assertEqual(resource.source, self.vh_xml_file)
        self.assertEqual(resource.root.tag, '{http://example.com/vehicles}vehicles')
        self.check_url(resource.url, self.vh_xml_file)
        self.assertIsNone(resource.text)
        with self.assertRaises(XMLResourceError) as ctx:
            resource.load()
        self.assertIn('cannot load a lazy resource', str(ctx.exception))
        self.assertIsNone(resource.text)

        resource = XMLResource(self.vh_xml_file, lazy=False)
        self.assertEqual(resource.source, self.vh_xml_file)
        self.assertEqual(resource.root.tag, '{http://example.com/vehicles}vehicles')
        self.check_url(resource.url, self.vh_xml_file)
        self.assertIsNone(resource.text)
        resource.load()
        self.assertTrue(resource.text.startswith('<?xml'))

    def test_xml_resource_from_element_tree(self):
        vh_etree = ElementTree.parse(self.vh_xml_file)
        vh_root = vh_etree.getroot()

        resource = XMLResource(vh_etree)
        self.assertEqual(resource.source, vh_etree)
        self.assertEqual(resource.root.tag, '{http://example.com/vehicles}vehicles')
        self.assertIsNone(resource.url)
        self.assertIsNone(resource.text)
        resource.load()
        self.assertIsNone(resource.text)

        resource = XMLResource(vh_root)
        self.assertEqual(resource.source, vh_root)
        self.assertEqual(resource.root.tag, '{http://example.com/vehicles}vehicles')
        self.assertIsNone(resource.url)
        self.assertIsNone(resource.text)
        resource.load()
        self.assertIsNone(resource.text)

    @unittest.skipIf(lxml_etree is None, "Skip: lxml is not available.")
    def test_xml_resource_from_lxml(self):
        vh_etree = lxml_etree.parse(self.vh_xml_file)
        vh_root = vh_etree.getroot()

        resource = XMLResource(vh_etree)
        self.assertEqual(resource.source, vh_etree)
        self.assertEqual(resource.root.tag, '{http://example.com/vehicles}vehicles')
        self.assertIsNone(resource.url)
        self.assertIsNone(resource.text)
        resource.load()
        self.assertIsNone(resource.text)

        resource = XMLResource(vh_root)
        self.assertEqual(resource.source, vh_root)
        self.assertEqual(resource.root.tag, '{http://example.com/vehicles}vehicles')
        self.assertIsNone(resource.url)
        self.assertIsNone(resource.text)
        resource.load()
        self.assertIsNone(resource.text)

        xml_text = resource.get_text()
        self.assertIn('<vh:vehicles ', xml_text)
        self.assertIn('<!-- Comment -->', xml_text)
        self.assertIn('</vh:vehicles>', xml_text)

    def test_xml_resource_from_resource(self):
        xml_file = urlopen('file://{}'.format(add_leading_slash(self.vh_xml_file)))
        try:
            resource = XMLResource(xml_file, lazy=False)
            self.assertEqual(resource.source, xml_file)
            self.assertEqual(resource.root.tag, '{http://example.com/vehicles}vehicles')
            self.assertIsNone(resource.url)
            self.assertIsNone(resource.text)
            resource.load()
            self.assertTrue(resource.text.startswith('<?xml'))
            self.assertFalse(xml_file.closed)
        finally:
            xml_file.close()

    def test_xml_resource_from_file(self):
        with open(self.vh_xsd_file) as schema_file:
            resource = XMLResource(schema_file, lazy=False)
            self.assertEqual(resource.source, schema_file)
            self.assertEqual(resource.root.tag, '{http://www.w3.org/2001/XMLSchema}schema')
            self.assertIsNone(resource.url)
            self.assertIsNone(resource.text)
            resource.load()
            self.assertTrue(resource.text.startswith('<xs:schema'))
            self.assertFalse(schema_file.closed)
            for _ in resource.iter():
                pass
            self.assertFalse(schema_file.closed)
            for _ in resource.iter_subtrees():
                pass
            self.assertFalse(schema_file.closed)

        with open(self.vh_xsd_file) as schema_file:
            resource = XMLResource(schema_file, lazy=False)
            self.assertEqual(resource.source, schema_file)
            self.assertEqual(resource.root.tag, '{http://www.w3.org/2001/XMLSchema}schema')
            self.assertIsNone(resource.url)
            self.assertIsNone(resource.text)
            resource.load()
            self.assertTrue(resource.text.startswith('<xs:schema'))
            self.assertFalse(schema_file.closed)
            for _ in resource.iter():
                pass
            self.assertFalse(schema_file.closed)
            for _ in resource.iter_subtrees():
                pass
            self.assertFalse(schema_file.closed)

    def test_xml_resource_from_string(self):
        with open(self.vh_xsd_file) as schema_file:
            schema_text = schema_file.read()

        resource = XMLResource(schema_text, lazy=False)
        self.assertEqual(resource.source, schema_text)
        self.assertEqual(resource.root.tag, '{http://www.w3.org/2001/XMLSchema}schema')
        self.assertIsNone(resource.url)
        self.assertTrue(resource.text.startswith('<xs:schema'))

        invalid_xml = '<tns0:root>missing namespace declaration</tns0:root>'
        with self.assertRaises(ElementTree.ParseError) as ctx:
            XMLResource(invalid_xml)

        self.assertEqual(str(ctx.exception), 'unbound prefix: line 1, column 0')

    def test_xml_resource_from_string_io(self):
        with open(self.vh_xsd_file) as schema_file:
            schema_text = schema_file.read()

        schema_file = StringIO(schema_text)
        resource = XMLResource(schema_file)
        self.assertEqual(resource.source, schema_file)
        self.assertEqual(resource.root.tag, '{http://www.w3.org/2001/XMLSchema}schema')
        self.assertIsNone(resource.url)
        self.assertTrue(resource.text.startswith('<xs:schema'))

        schema_file = StringIO(schema_text)
        resource = XMLResource(schema_file, lazy=False)
        self.assertEqual(resource.source, schema_file)
        self.assertEqual(resource.root.tag, '{http://www.w3.org/2001/XMLSchema}schema')
        self.assertIsNone(resource.url)
        self.assertTrue(resource.text.startswith('<xs:schema'))

    def test_xml_resource_from_wrong_arguments(self):
        self.assertRaises(TypeError, XMLResource, [b'<UNSUPPORTED_DATA_TYPE/>'])

        with self.assertRaises(TypeError) as ctx:
            XMLResource('<root/>', base_url=b'/home')
        self.assertIn(' ', str(ctx.exception))

    def test_xml_resource_namespace(self):
        resource = XMLResource(self.vh_xml_file)
        self.assertEqual(resource.namespace, 'http://example.com/vehicles')
        resource = XMLResource(self.vh_xsd_file)
        self.assertEqual(resource.namespace, 'http://www.w3.org/2001/XMLSchema')
        resource = XMLResource(self.col_xml_file)
        self.assertEqual(resource.namespace, 'http://example.com/ns/collection')
        self.assertEqual(XMLResource('<A/>').namespace, '')

    def test_xml_resource_access(self):
        resource = XMLResource(self.vh_xml_file)
        base_url = resource.base_url

        XMLResource(self.vh_xml_file, allow='local')
        XMLResource(
            self.vh_xml_file, base_url=os.path.dirname(self.vh_xml_file), allow='sandbox'
        )

        with self.assertRaises(XMLResourceError) as ctx:
            XMLResource(self.vh_xml_file, allow='remote')
        self.assertTrue(str(ctx.exception).startswith("block access to local resource"))

        with self.assertRaises(URLError) as ctx:
            XMLResource("https://xmlschema.test/vehicles.xsd", allow='remote')
        self.assertIn("Name or service not known", str(ctx.exception))

        with self.assertRaises(XMLResourceError) as ctx:
            XMLResource("https://xmlschema.test/vehicles.xsd", allow='local')
        self.assertEqual(str(ctx.exception),
                         "block access to remote resource https://xmlschema.test/vehicles.xsd")

        with self.assertRaises(XMLResourceError) as ctx:
            XMLResource("https://xmlschema.test/vehicles.xsd", allow='sandbox')
        self.assertEqual(str(ctx.exception),
                         "block access to files out of sandbox requires 'base_url' to be set")

        with self.assertRaises(XMLResourceError) as ctx:
            XMLResource("/tmp/vehicles.xsd", allow='sandbox')
        self.assertEqual(
            str(ctx.exception),
            "block access to files out of sandbox requires 'base_url' to be set",
        )

        source = "/tmp/vehicles.xsd"
        with self.assertRaises(XMLResourceError) as ctx:
            XMLResource(source, base_url=base_url, allow='sandbox')
        self.assertEqual(
            str(ctx.exception),
            "block access to out of sandbox file {}".format(normalize_url(source)),
        )

        with self.assertRaises(TypeError) as ctx:
            XMLResource("https://xmlschema.test/vehicles.xsd", allow=None)
        self.assertEqual(str(ctx.exception),
                         "invalid type <class 'NoneType'> for the attribute 'allow'")

        with self.assertRaises(ValueError) as ctx:
            XMLResource("https://xmlschema.test/vehicles.xsd", allow='any')
        self.assertEqual(str(ctx.exception),
                         "'allow' attribute: 'any' is not a security mode")

    def test_xml_resource_defuse(self):
        resource = XMLResource(self.vh_xml_file, defuse='never', lazy=True)
        self.assertEqual(resource.defuse, 'never')
        self.assertRaises(ValueError, XMLResource, self.vh_xml_file, defuse='all')
        self.assertRaises(TypeError, XMLResource, self.vh_xml_file, defuse=None)
        self.assertIsInstance(resource.root, etree_element)
        resource = XMLResource(self.vh_xml_file, defuse='always', lazy=True)
        self.assertIsInstance(resource.root, py_etree_element)

        xml_file = casepath('resources/with_entity.xml')
        self.assertIsInstance(XMLResource(xml_file, lazy=True), XMLResource)
        with self.assertRaises(ElementTree.ParseError):
            XMLResource(xml_file, defuse='always', lazy=True)

        xml_file = casepath('resources/unused_external_entity.xml')
        self.assertIsInstance(XMLResource(xml_file, lazy=True), XMLResource)
        with self.assertRaises(ElementTree.ParseError):
            XMLResource(xml_file, defuse='always', lazy=True)

    def test_xml_resource_defuse_other_source_types(self):
        xml_file = casepath('resources/external_entity.xml')
        self.assertIsInstance(XMLResource(xml_file, lazy=True), XMLResource)

        with self.assertRaises(ElementTree.ParseError):
            XMLResource(xml_file, defuse='always', lazy=True)

        with self.assertRaises(ElementTree.ParseError):
            XMLResource(xml_file, defuse='always', lazy=False)

        with self.assertRaises(ElementTree.ParseError):
            XMLResource(xml_file, defuse='always', lazy=True)

        with self.assertRaises(ElementTree.ParseError):
            with open(xml_file) as fp:
                XMLResource(fp, defuse='always', lazy=False)

        with self.assertRaises(ElementTree.ParseError):
            with open(xml_file) as fp:
                XMLResource(fp.read(), defuse='always', lazy=False)

        with self.assertRaises(ElementTree.ParseError):
            with open(xml_file) as fp:
                XMLResource(StringIO(fp.read()), defuse='always', lazy=False)

    def test_xml_resource_timeout(self):
        resource = XMLResource(self.vh_xml_file, timeout=30)
        self.assertEqual(resource.timeout, 30)
        self.assertRaises(TypeError, XMLResource, self.vh_xml_file, timeout='100')
        self.assertRaises(ValueError, XMLResource, self.vh_xml_file, timeout=0)

    def test_xml_resource_laziness(self):
        resource = XMLResource(self.vh_xml_file, lazy=True)
        self.assertTrue(resource.is_lazy())
        resource = XMLResource(self.vh_xml_file, lazy=False)
        self.assertFalse(resource.is_lazy())
        resource = XMLResource(self.vh_xml_file, lazy=1)
        self.assertTrue(resource.is_lazy())
        resource = XMLResource(self.vh_xml_file, lazy=2)
        self.assertTrue(resource.is_lazy())
        resource = XMLResource(self.vh_xml_file, lazy=0)
        self.assertFalse(resource.is_lazy())

        with self.assertRaises(ValueError):
            XMLResource(self.vh_xml_file, lazy=-1)

        with self.assertRaises(TypeError):
            XMLResource(self.vh_xml_file, lazy='1')

    def test_xml_resource_base_url(self):
        resource = XMLResource(self.vh_xml_file)
        base_url = resource.base_url
        self.assertEqual(base_url, XMLResource(self.vh_xml_file, '/other').base_url)

        with open(self.vh_xml_file) as fp:
            self.assertIsNone(XMLResource(fp.read()).base_url)

        with open(self.vh_xml_file) as fp:
            resource = XMLResource(fp.read(), base_url='/foo')
            self.assertEqual(resource.base_url, '/foo')

        resource.base_url = '/bar'
        self.assertEqual(resource.base_url, '/bar')

    def test_xml_resource_is_local(self):
        resource = XMLResource(self.vh_xml_file)
        self.assertTrue(resource.is_local())

    def test_xml_resource_is_remote(self):
        resource = XMLResource(self.vh_xml_file)
        self.assertFalse(resource.is_remote())

    def test_xml_resource_is_loaded(self):
        resource = XMLResource(self.vh_xml_file, lazy=False)
        self.assertFalse(resource.is_loaded())
        resource.load()
        self.assertTrue(resource.is_loaded())

    def test_xml_resource__etree_iterparse(self):
        resource = XMLResource(self.vh_xml_file)

        self.assertEqual(resource.defuse, 'remote')
        for _, elem in resource._etree_iterparse(self.col_xml_file, events=('end',)):
            self.assertTrue(is_etree_element(elem))

        resource.defuse = 'always'
        for _, elem in resource._etree_iterparse(self.col_xml_file, events=('end',)):
            self.assertTrue(is_etree_element(elem))

    def test_xml_resource_protected_parse(self):
        resource = XMLResource(self.vh_xml_file, lazy=False)

        self.assertEqual(resource.defuse, 'remote')
        with open(self.col_xml_file) as fp:
            resource._parse(fp, lazy=False)
        self.assertTrue(is_etree_element(resource.root))

        resource.defuse = 'always'
        with open(self.col_xml_file) as fp:
            resource._parse(fp, lazy=False)
        self.assertTrue(is_etree_element(resource.root))

        resource = XMLResource(self.vh_xml_file, lazy=True)
        with open(self.col_xml_file) as fp:
            resource._parse(fp, lazy=True)
        self.assertTrue(is_etree_element(resource.root))

    def test_xml_resource_tostring(self):
        resource = XMLResource(self.vh_xml_file)
        self.assertTrue(resource.tostring().startswith('<vh:vehicles'))

    def test_xml_resource_copy(self):
        resource = XMLResource(self.vh_xml_file, lazy=True)
        resource2 = resource.copy(defuse='never')
        self.assertEqual(resource2.defuse, 'never')
        resource2 = resource.copy(timeout=30)
        self.assertEqual(resource2.timeout, 30)
        resource2 = resource.copy(lazy=False)
        self.assertFalse(resource2.is_lazy())

        self.assertIsNone(resource.text)
        self.assertIsNone(resource2.text)

        with self.assertRaises(XMLResourceError) as ctx:
            resource.load()
        self.assertIn('cannot load a lazy resource', str(ctx.exception))

        resource2.load()
        self.assertIsNotNone(resource2.text)
        resource3 = resource2.copy()
        self.assertEqual(resource2.text, resource3.text)

    def test_xml_resource_open(self):
        resource = XMLResource(self.vh_xml_file)
        xml_file = resource.open()
        self.assertIsNot(xml_file, resource.source)
        data = xml_file.read().decode('utf-8')
        self.assertTrue(data.startswith('<?xml '))
        xml_file.close()

        resource._url = 'file:not-a-file'
        with self.assertRaises(XMLResourceError):
            resource.open()

        resource = XMLResource('<A/>')
        self.assertRaises(XMLResourceError, resource.open)

        resource = XMLResource(source=open(self.vh_xml_file))
        xml_file = resource.open()
        self.assertIs(xml_file, resource.source)
        xml_file.close()

    def test_xml_resource_seek(self):
        resource = XMLResource(self.vh_xml_file)
        self.assertIsNone(resource.seek(0))
        self.assertIsNone(resource.seek(1))
        xml_file = open(self.vh_xml_file)
        resource = XMLResource(source=xml_file)
        self.assertEqual(resource.seek(0), 0)
        self.assertEqual(resource.seek(1), 1)
        xml_file.close()

    def test_xml_resource_close(self):
        resource = XMLResource(self.vh_xml_file)
        resource.close()
        xml_file = resource.open()
        self.assertTrue(callable(xml_file.read))

        with open(self.vh_xml_file) as xml_file:
            resource = XMLResource(source=xml_file)
            resource.close()
            with self.assertRaises(ValueError):
                resource.open()

    def test_xml_resource_iter(self):
        resource = XMLResource(self.schema_class.meta_schema.source.url)
        self.assertFalse(resource.is_lazy())
        lazy_resource = XMLResource(self.schema_class.meta_schema.source.url, lazy=True)
        self.assertTrue(lazy_resource.is_lazy())

        tags = [x.tag for x in resource.iter()]
        self.assertEqual(len(tags), 1390)
        self.assertEqual(tags[0], '{%s}schema' % XSD_NAMESPACE)

        lazy_tags = [x.tag for x in lazy_resource.iter()]
        self.assertEqual(len(lazy_tags), 1390)
        self.assertEqual(lazy_tags[-1], '{%s}schema' % XSD_NAMESPACE)
        self.assertNotEqual(tags, lazy_tags)

        tags = [x.tag for x in resource.iter('{%s}complexType' % XSD_NAMESPACE)]
        self.assertEqual(len(tags), 56)
        self.assertEqual(tags[0], '{%s}complexType' % XSD_NAMESPACE)
        self.assertListEqual(
            tags, [x.tag for x in lazy_resource.iter('{%s}complexType' % XSD_NAMESPACE)]
        )

    def test_xml_resource_iter_subtrees(self):
        namespaces = {'xs': XSD_NAMESPACE}
        resource = XMLResource(self.schema_class.meta_schema.source.url)
        self.assertFalse(resource.is_lazy())
        lazy_resource = XMLResource(self.schema_class.meta_schema.source.url, lazy=True)
        self.assertTrue(lazy_resource.is_lazy())

        # Note: Element change with lazy resource so compare only tags

        tags = [x.tag for x in resource.iter_subtrees()]
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0], '{%s}schema' % XSD_NAMESPACE)

        lazy_tags = [x.tag for x in lazy_resource.iter_subtrees()]
        self.assertListEqual(tags, lazy_tags)

        lazy_tags = [x.tag for x in lazy_resource.iter_subtrees(lazy_mode=2)]
        self.assertListEqual(tags, lazy_tags)

        lazy_tags = [x.tag for x in lazy_resource.iter_subtrees(lazy_mode=3)]
        self.assertEqual(len(lazy_tags), 156)

        lazy_tags = [x.tag for x in lazy_resource.iter_subtrees(lazy_mode=4)]
        self.assertEqual(len(lazy_tags), 157)
        self.assertEqual(tags[0], lazy_tags[-1])

        lazy_tags = [x.tag for x in lazy_resource.iter_subtrees(lazy_mode=5)]
        self.assertEqual(len(lazy_tags), 158)
        self.assertEqual(tags[0], lazy_tags[0])
        self.assertEqual(tags[0], lazy_tags[-1])

        tags = [x.tag for x in resource.iter_subtrees(path='.')]
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0], '{%s}schema' % XSD_NAMESPACE)
        lazy_tags = [x.tag for x in lazy_resource.iter_subtrees(path='.')]
        self.assertListEqual(tags, lazy_tags)

        tags = [x.tag for x in resource.iter_subtrees(path='*')]
        self.assertEqual(len(tags), 156)
        self.assertEqual(tags[0], '{%s}annotation' % XSD_NAMESPACE)
        lazy_tags = [x.tag for x in lazy_resource.iter_subtrees(path='*')]
        self.assertListEqual(tags, lazy_tags)

        tags = [x.tag for x in resource.iter_subtrees('xs:complexType', namespaces)]
        self.assertEqual(len(tags), 35)
        self.assertTrue(all(t == '{%s}complexType' % XSD_NAMESPACE for t in tags))
        lazy_tags = [x.tag for x in lazy_resource.iter_subtrees('xs:complexType', namespaces)]
        self.assertListEqual(tags, lazy_tags)

        tags = [x.tag for x in resource.iter_subtrees('. /. / xs:complexType', namespaces)]
        self.assertEqual(len(tags), 35)
        self.assertTrue(all(t == '{%s}complexType' % XSD_NAMESPACE for t in tags))
        lazy_tags = [
            x.tag for x in lazy_resource.iter_subtrees('. /. / xs:complexType', namespaces)
        ]
        self.assertListEqual(tags, lazy_tags)

    def test_xml_resource_get_namespaces(self):
        with open(self.vh_xml_file) as schema_file:
            resource = XMLResource(schema_file)
            self.assertIsNone(resource.url)
            self.assertEqual(set(resource.get_namespaces().keys()), {'vh', 'xsi'})
            self.assertFalse(schema_file.closed)

        with open(self.vh_xsd_file) as schema_file:
            resource = XMLResource(schema_file)
            self.assertIsNone(resource.url)
            self.assertEqual(set(resource.get_namespaces().keys()), {'xs', 'vh'})
            self.assertFalse(schema_file.closed)

        resource = XMLResource(self.col_xml_file)
        self.assertEqual(resource.url, normalize_url(self.col_xml_file))
        self.assertEqual(set(resource.get_namespaces().keys()), {'col', 'xsi'})

        resource = XMLResource(self.col_xsd_file)
        self.assertEqual(resource.url, normalize_url(self.col_xsd_file))
        self.assertEqual(set(resource.get_namespaces().keys()), {'', 'xs'})

        resource = XMLResource("""<?xml version="1.0" ?>
            <root xmlns="tns1">
                <tns:elem1 xmlns:tns="tns1" xmlns="unknown"/>
            </root>""", lazy=False)
        self.assertEqual(set(resource.get_namespaces().keys()), {'', 'tns', 'default'})
        resource._lazy = True
        self.assertEqual(resource.get_namespaces().keys(), {''})

        resource = XMLResource("""<?xml version="1.0" ?>
            <root xmlns:tns="tns1">
                <tns:elem1 xmlns:tns="tns1" xmlns="unknown"/>
            </root>""", lazy=False)
        self.assertEqual(set(resource.get_namespaces().keys()), {'default', 'tns'})
        self.assertEqual(resource.get_namespaces(root_only=True).keys(), {'tns'})
        resource._lazy = True
        self.assertEqual(resource.get_namespaces().keys(), {'tns'})

        resource = XMLResource("""<?xml version="1.0" ?>
            <root xmlns:tns="tns1">
                <tns:elem1 xmlns:tns="tns3" xmlns="unknown"/>
            </root>""", lazy=False)
        self.assertEqual(set(resource.get_namespaces().keys()), {'default', 'tns', 'tns0'})
        resource._lazy = True
        self.assertEqual(resource.get_namespaces().keys(), {'tns'})

    def test_xml_resource_get_locations(self):
        resource = XMLResource(self.col_xml_file)
        self.check_url(resource.url, normalize_url(self.col_xml_file))
        locations = resource.get_locations([('ns', 'other.xsd')])
        self.assertEqual(len(locations), 2)
        self.check_url(locations[0][1], os.path.join(self.col_dir, 'other.xsd'))
        self.check_url(locations[1][1], normalize_url(self.col_xsd_file))

    @unittest.skipIf(SKIP_REMOTE_TESTS or platform.system() == 'Windows',
                     "Remote networks are not accessible or avoid SSL "
                     "verification error on Windows.")
    def test_remote_resource_loading(self):
        with urlopen("https://raw.githubusercontent.com/brunato/xmlschema/master/"
                     "tests/test_cases/examples/collection/collection.xsd") as rh:
            col_xsd_resource = XMLResource(rh)

        self.assertEqual(col_xsd_resource.namespace, XSD_NAMESPACE)
        self.assertIsNone(col_xsd_resource.seek(0))

        col_schema = self.schema_class(col_xsd_resource.get_text())
        self.assertTrue(isinstance(col_schema, self.schema_class))

        vh_schema = self.schema_class("https://raw.githubusercontent.com/brunato/xmlschema/master/"
                                      "tests/test_cases/examples/vehicles/vehicles.xsd")
        self.assertTrue(isinstance(vh_schema, self.schema_class))
        self.assertTrue(vh_schema.source.is_remote())

    def test_schema_defuse(self):
        vh_schema = self.schema_class(self.vh_xsd_file, defuse='always')
        self.assertIsInstance(vh_schema.root, etree_element)
        for schema in vh_schema.maps.iter_schemas():
            self.assertIsInstance(schema.root, etree_element)

    def test_schema_resource_access(self):
        vh_schema = self.schema_class(self.vh_xsd_file, allow='sandbox')
        self.assertTrue(isinstance(vh_schema, self.schema_class))

        xsd_source = """
        <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" 
                xmlns:vh="http://example.com/vehicles">
            <xs:import namespace="http://example.com/vehicles" schemaLocation="{}"/>
        </xs:schema>""".format(self.vh_xsd_file)

        schema = self.schema_class(xsd_source, allow='all')
        self.assertTrue(isinstance(schema, self.schema_class))
        self.assertIn("http://example.com/vehicles", schema.maps.namespaces)
        self.assertEqual(len(schema.maps.namespaces["http://example.com/vehicles"]), 4)

        with warnings.catch_warnings(record=True) as ctx:
            warnings.simplefilter("always")
            self.schema_class(xsd_source, allow='remote')
            self.assertEqual(len(ctx), 1, "Expected one import warning")
            self.assertIn("block access to local resource", str(ctx[0].message))

        schema = self.schema_class(xsd_source, allow='local')
        self.assertTrue(isinstance(schema, self.schema_class))
        self.assertIn("http://example.com/vehicles", schema.maps.namespaces)
        self.assertEqual(len(schema.maps.namespaces["http://example.com/vehicles"]), 4)

        with self.assertRaises(XMLResourceError) as ctx:
            self.schema_class(xsd_source, allow='sandbox')
        self.assertIn("block access to files out of sandbox", str(ctx.exception))

        schema = self.schema_class(
            xsd_source, base_url=os.path.dirname(self.vh_xsd_file), allow='all'
        )
        self.assertTrue(isinstance(schema, self.schema_class))
        self.assertIn("http://example.com/vehicles", schema.maps.namespaces)
        self.assertEqual(len(schema.maps.namespaces["http://example.com/vehicles"]), 4)

        with warnings.catch_warnings(record=True) as ctx:
            warnings.simplefilter("always")
            self.schema_class(xsd_source, base_url='/improbable', allow='sandbox')
            self.assertEqual(len(ctx), 1, "Expected one import warning")
            self.assertIn("block access to out of sandbox", str(ctx[0].message))

    def test_fid_with_name_attr(self):
        """XMLResource gets correct data when passed a file like object
        with a name attribute that isn't on disk.

        These file descriptors appear when working with the contents from a
        zip using the zipfile module and with Django files in some
        instances.
        """
        class FileProxy(object):
            def __init__(self, fid, fake_name):
                self._fid = fid
                self.name = fake_name

            def __getattr__(self, attr):
                try:
                    return self.__dict__[attr]
                except (KeyError, AttributeError):
                    return getattr(self.__dict__["_fid"], attr)

        with open(self.vh_xml_file) as xml_file:
            resource = XMLResource(FileProxy(xml_file, fake_name="not__on____disk.xml"))
            self.assertIsNone(resource.url)
            self.assertEqual(set(resource.get_namespaces().keys()), {'vh', 'xsi'})
            self.assertFalse(xml_file.closed)


if __name__ == '__main__':
    header_template = "Test xmlschema's XML resources with Python {} on platform {}"
    header = header_template.format(platform.python_version(), platform.platform())
    print('{0}\n{1}\n{0}'.format("*" * len(header), header))

    unittest.main()
