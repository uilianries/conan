import mock
import unittest

from parameterized import parameterized

from conans.client import tools
from conans.client.conf.detect import detect_defaults_settings
from conans.paths import DEFAULT_PROFILE_NAME
from conans.test.utils.mocks import TestBufferConanOutput


class DetectTest(unittest.TestCase):
    @mock.patch("platform.machine", return_value="")
    def test_detect_empty_arch(self, _):
        result = detect_defaults_settings(output=TestBufferConanOutput(),
                                          profile_path=DEFAULT_PROFILE_NAME)
        result = dict(result)
        self.assertTrue("arch" not in result)
        self.assertTrue("arch_build" not in result)

    @mock.patch("conans.client.conf.detect._gcc_compiler", return_value=("gcc", "8"))
    def test_detect_custom_profile(self, _):
        output = TestBufferConanOutput()
        with tools.environment_append({"CC": "gcc"}):
            detect_defaults_settings(output, profile_path="~/.conan/profiles/mycustomprofile")
            self.assertIn("conan profile update settings.compiler.libcxx=libstdc++11 "
                          "mycustomprofile", output)

    @mock.patch("conans.client.conf.detect._gcc_compiler", return_value=("gcc", "8"))
    def test_detect_default_profile(self, _):
        output = TestBufferConanOutput()
        with tools.environment_append({"CC": "gcc"}):
            detect_defaults_settings(output, profile_path="~/.conan/profiles/default")
            self.assertIn("conan profile update settings.compiler.libcxx=libstdc++11 default",
                          output)

    @mock.patch("conans.client.conf.detect._gcc_compiler", return_value=("gcc", "8"))
    def test_detect_file_profile(self, _):
        output = TestBufferConanOutput()
        with tools.environment_append({"CC": "gcc"}):
            detect_defaults_settings(output, profile_path="./MyProfile")
            self.assertIn("conan profile update settings.compiler.libcxx=libstdc++11 MyProfile",
                          output)

    @mock.patch("conans.client.conf.detect._gcc_compiler", return_value=("gcc", "8"))
    def test_detect_abs_file_profile(self, _):
        output = TestBufferConanOutput()
        with tools.environment_append({"CC": "gcc"}):
            detect_defaults_settings(output, profile_path="/foo/bar/quz/custom-profile")
            self.assertIn("conan profile update settings.compiler.libcxx=libstdc++11 "
                          "custom-profile", output)

    @parameterized.expand([
        ['powerpc', '64', '7.1.0.0', 'ppc64'],
        ['powerpc', '32', '7.1.0.0', 'ppc32'],
        ['rs6000', None, '4.2.1.0', 'ppc32']
    ])
    def test_detect_aix(self, processor, bitness, version, expected_arch):
        with mock.patch("platform.machine", mock.MagicMock(return_value='XXXXXXXXXXXX')), \
                mock.patch("platform.processor", mock.MagicMock(return_value=processor)), \
                mock.patch("platform.system", mock.MagicMock(return_value='AIX')), \
                mock.patch("conans.client.tools.oss.OSInfo.get_aix_conf", mock.MagicMock(return_value=bitness)), \
                mock.patch('subprocess.check_output', mock.MagicMock(return_value=version)):
            result = detect_defaults_settings(output=TestBufferConanOutput(),
                                              profile_path=DEFAULT_PROFILE_NAME)
            result = dict(result)
            self.assertEqual("AIX", result['os'])
            self.assertEqual("AIX", result['os_build'])
            self.assertEqual(expected_arch, result['arch'])
            self.assertEqual(expected_arch, result['arch_build'])
