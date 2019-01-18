import unittest

from nose.plugins.attrib import attr

from conans import tools
from conans.test.utils.tools import TestClient


CONAN_RECIPE = """
from conans import ConanFile, CMake

class FooConan(ConanFile):
    name = "foo"
    version = "0.1"
    settings = "os_build", "compiler", "build_type"
    generators = "cmake"

    def build(self):
        cmake = CMake(self, generator="{}")
        cmake.configure()
"""


CPP_CONTENT = """
int main() {}
"""

CMAKE_RECIPE = """
cmake_minimum_required(VERSION 2.8.12)
project(dummy CXX)

include(${CMAKE_BINARY_DIR}/conanbuildinfo.cmake)
conan_basic_setup()

add_executable(dummy dummy.cpp)
"""


class CMakeGeneratorTest(unittest.TestCase):

    def _check_build_generator(self, generator):
        client = TestClient()
        client.save({"conanfile.py": CONAN_RECIPE.format(generator),
                     "CMakeLists.txt": CMAKE_RECIPE,
                     "dummy.cpp": CPP_CONTENT})

        client.run("install .")
        client.run("build .")
        self.assertIn("Check for working CXX compiler", client.out)
        self.assertIn('cmake -G "{}"'.format(generator), client.out)

    @unittest.skipUnless(tools.os_info.is_linux, "Compilation with real gcc needed")
    def test_cmake_default_generator_linux(self):
        self._check_build_generator("Unix Makefiles")

    @unittest.skipUnless(tools.os_info.is_windows, "MinGW is only supported on Windows")
    def test_cmake_default_generator_windows(self):
        self._check_build_generator("MinGW Makefiles")

    @unittest.skipUnless(tools.os_info.is_macos, "Compilation with real clang is needed")
    def test_cmake_default_generator_osx(self):
        self._check_build_generator("Unix Makefiles")
