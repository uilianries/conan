import textwrap
import unittest
import platform
import os
import pytest

from conans.client.tools.files import which
from conan.tools.microsoft.visual import vcvars_command
from conan.tools.cmake.base import CMakeToolchainBase
from conans.test.functional.utils import check_vs_runtime, check_msvc_library
from conans.test.utils.tools import TestClient
from conans.test.functional.toolchains.ios._utils import create_library


@pytest.mark.tool_cmake
class TestCMakeNinja:
    # This test assumes that 'CMake' and 'Ninja' are available in the system

    conanfile = textwrap.dedent("""
        from conans import ConanFile
        from conan.tools.cmake import CMake, CMakeToolchain

        class Library(ConanFile):
            name = 'hello'
            version = '1.0'
            settings = 'os', 'arch', 'compiler', 'build_type'
            exports_sources = 'hello.h', 'hello.cpp', 'CMakeLists.txt'
            options = {'shared': [True, False]}
            default_options = {'shared': False}
            _cmake = None

            def _configure_cmake(self):
                if not self._cmake:
                    self._cmake = CMake(self, generator="Ninja", parallel=False)
                    self._cmake.configure()
                return self._cmake

            def generate(self):
                tc = CMakeToolchain(self)
                tc.generate()

            def build(self):
                cmake = self._configure_cmake()
                cmake.configure()
                cmake.build()

            def package(self):
                cmake = self._configure_cmake()
                cmake.install()
        """)

    @classmethod
    def setup_class(cls):
        if not which("ninja"):
            raise unittest.SkipTest("Ninja expected in PATH")

    def setup_method(self):
        self.client = TestClient(path_with_spaces=False)
        create_library(self.client)
        self.client.save({'conanfile.py': self.conanfile})

    @pytest.mark.skipif(platform.system() != "Linux", reason="Only Linux")
    @pytest.mark.parametrize("build_type,shared", [("Release", False), ("Debug", True)])
    @pytest.mark.tool_compiler
    def test_locally_build_linux(self, build_type, shared):
        """ Ninja build must proceed using default profile and cmake build (Linux)
        """
        print(self.client.current_folder)
        self.client.run('install . -s os=Linux -s arch=x86_64 -s build_type={} -o hello:shared={}'
                        .format(build_type, shared))
        self.client.run_command('cmake . -G"Ninja" -DCMAKE_TOOLCHAIN_FILE={}'
                                .format(CMakeToolchainBase.filename))
        ninja_build_file = open(os.path.join(self.client.current_folder, 'build.ninja'), 'r').read()
        assert "CONFIGURATION = {}".format(build_type) in ninja_build_file

        self.client.run_command('ninja')
        if shared:
            assert "Linking CXX shared library libhello.so" in self.client.out
            self.client.run_command("objdump -f libhello.so")
            assert "architecture: i386:x86-64" in self.client.out
            assert "DYNAMIC" in self.client.out
        else:
            assert "Linking CXX static library libhello.a" in self.client.out
            self.client.run_command("objdump -f libhello.a")
            assert "architecture: i386:x86-64"in  self.client.out

    @pytest.mark.skipif(platform.system() != "Windows", reason="Only windows")
    @pytest.mark.parametrize("build_type,shared", [("Release", False), ("Debug", True)])
    @pytest.mark.tool_compiler
    def test_locally_build_windows(self, build_type, shared):
        """ Ninja build must proceed using default profile and cmake build (Windows Release)
        """
        self.client.run("install . -s os=Windows -s arch=x86_64 -s compiler='Visual Studio'"
                        " -s compiler.version=16 -s build_type={} -o hello:shared={}"
                        .format(build_type, shared))
        # Ninja is single-configuration
        vcvars = vcvars_command("16", architecture="amd64")
        self.client.run_command('{} && cmake . -G "Ninja" '
                                '-DCMAKE_TOOLCHAIN_FILE=conan_toolchain.cmake'.format(vcvars))

        # self.client.run_command("{} && cmake --build .".format(vcvars))
        self.client.run_command("{} && ninja".format(vcvars))

        # TODO
        # self.assertIn("main: {}!".format(build_type), self.client.out)
        # check_msvc_library("")



    @pytest.mark.skipif(platform.system() != "Windows", reason="Only windows")
    @pytest.mark.parametrize("build_type,shared", [("Release", False), ("Debug", True)])
    @pytest.mark.tool_compiler
    def test_locally_build_windows_debug(self, build_type, shared):
        """ Ninja build must proceed using default profile and cmake build (Windows Debug)
        """
        self.client = TestClient(path_with_spaces=False)
        self.client.save({"conanfile.py": self.conanfile,
                     "main.cpp": self.main_cpp,
                     "CMakeLists.txt": self.cmake})
        win_host = textwrap.dedent("""
            [settings]
            os=Windows
            arch=x86
            compiler=Visual Studio
            compiler.version=15
            compiler.runtime=MTd
            build_type=Debug
             """)
        self.client.save({"win": win_host})
        self.client.run("install . -pr=win")
        # Ninja is single-configuration
        # It is necessary to set architecture=x86 here, otherwise final architecture is wrong
        vcvars = vcvars_command("15", architecture="x86")
        self.client.run("install . -pr=win")
        self.client.run_command('{} && cmake . -G "Ninja" -DCMAKE_TOOLCHAIN_FILE=conan_toolchain.cmake '
                           .format(vcvars))
        self.client.run_command("{} && cmake --build .".format(vcvars))
        self.client.run_command("App")
        assert "main: Debug!" in self.client.out
        assert "main _M_IX86 defined" in self.client.out
        assert "main _MSC_VER19" in self.client.out
        assert "main _MSVC_LANG2014" in self.client.out

        check_vs_runtime("App.exe", self.client, "15", build_type="Debug", static=True)

    @pytest.mark.skipif(platform.system() != "Darwin", reason="Requires apple-clang")
    @pytest.mark.parametrize("build_type,shared", [("Release", False), ("Debug", True)])
    @pytest.mark.tool_compiler
    def test_locally_build_macos(self, build_type, shared):
        self.client.run(
            'install . -s os=Macos -s arch=x86_64 -s build_type={} -o hello:shared={}'
            .format(build_type, shared))
        self.client.run_command('cmake . -G"Ninja" -DCMAKE_TOOLCHAIN_FILE={}'
                                .format(CMakeToolchainBase.filename))
        ninja_build_file = open(os.path.join(self.client.current_folder, 'build.ninja'), 'r').read()
        assert "CONFIGURATION = {}".format(build_type) in ninja_build_file

        self.client.run_command('ninja')
        if shared:
            assert "Linking CXX shared library libhello.dylib" in self.client.out
            self.client.run_command("lipo -info libhello.dylib")
            assert "Non-fat file: libhello.dylib is architecture: x86_64" in self.client.out
        else:
            assert "Linking CXX static library libhello.a" in self.client.out
            self.client.run_command("lipo -info libhello.a")
            assert "Non-fat file: libhello.a is architecture: x86_64" in self.client.out
