import os
import platform
import textwrap
import unittest

import pytest

from conans.test.assets.genconanfile import GenConanfile
from conans.test.utils.tools import TestClient
from conans.util.files import load


class PkgGeneratorTest(unittest.TestCase):

    # Without compiler, def rpath_flags(settings, os_build, lib_paths): doesn't append the -Wl...etc
    @pytest.mark.tool_compiler
    def test_pkg_config_dirs(self):
        # https://github.com/conan-io/conan/issues/2756
        conanfile = """
import os
from conans import ConanFile

class PkgConfigConan(ConanFile):
    name = "MyLib"
    version = "0.1"

    def package_info(self):
        self.cpp_info.frameworkdirs = []
        self.cpp_info.filter_empty = False
        libname = "mylib"
        fake_dir = os.path.join("/", "my_absoulte_path", "fake")
        include_dir = os.path.join(fake_dir, libname, "include")
        lib_dir = os.path.join(fake_dir, libname, "lib")
        lib_dir2 = os.path.join(self.package_folder, "lib2")
        self.cpp_info.includedirs = [include_dir]
        self.cpp_info.libdirs = [lib_dir, lib_dir2]
"""
        client = TestClient()
        client.save({"conanfile.py": conanfile})
        client.run("create . danimtb/testing")
        client.run("install MyLib/0.1@danimtb/testing -g pkg_config")

        pc_path = os.path.join(client.current_folder, "MyLib.pc")
        self.assertTrue(os.path.exists(pc_path))
        pc_content = load(pc_path)
        expected_rpaths = ""
        if platform.system() in ("Linux", "Darwin"):
            expected_rpaths = ' -Wl,-rpath,"${libdir}" -Wl,-rpath,"${libdir2}"'
        expected_content = """libdir=/my_absoulte_path/fake/mylib/lib
libdir2=${prefix}/lib2
includedir=/my_absoulte_path/fake/mylib/include

Name: MyLib
Description: Conan package: MyLib
Version: 0.1
Libs: -L"${libdir}" -L"${libdir2}"%s
Cflags: -I"${includedir}"\
""" % expected_rpaths
        self.assertEqual("\n".join(pc_content.splitlines()[1:]), expected_content)

        def assert_is_abs(path):
            self.assertTrue(os.path.isabs(path))

        for line in pc_content.splitlines():
            if line.startswith("includedir="):
                assert_is_abs(line[len("includedir="):])
                self.assertTrue(line.endswith("include"))
            elif line.startswith("libdir="):
                assert_is_abs(line[len("libdir="):])
                self.assertTrue(line.endswith("lib"))
            elif line.startswith("libdir3="):
                self.assertIn("${prefix}/lib2", line)

    def test_pkg_config_without_libdir(self):
        conanfile = """
import os
from conans import ConanFile

class PkgConfigConan(ConanFile):
    name = "MyLib"
    version = "0.1"

    def package_info(self):
        self.cpp_info.includedirs = []
        self.cpp_info.libdirs = []
        self.cpp_info.bindirs = []
        self.cpp_info.libs = []
"""
        client = TestClient()
        client.save({"conanfile.py": conanfile})
        client.run("create . danimtb/testing")
        client.run("install MyLib/0.1@danimtb/testing -g pkg_config")

        pc_path = os.path.join(client.current_folder, "MyLib.pc")
        self.assertTrue(os.path.exists(pc_path))
        pc_content = load(pc_path)
        expected = textwrap.dedent("""
            Name: MyLib
            Description: Conan package: MyLib
            Version: 0.1
            Libs:%s
            Cflags: """ % " ")  # ugly hack for trailing whitespace removed by IDEs
        self.assertEqual("\n".join(pc_content.splitlines()[1:]), expected)

    def test_pkg_config_rpaths(self):
        # rpath flags are only generated for gcc and clang
        profile = """
[settings]
os=Linux
compiler=gcc
compiler.version=7
compiler.libcxx=libstdc++
"""
        conanfile = """
from conans import ConanFile

class PkgConfigConan(ConanFile):
    name = "MyLib"
    version = "0.1"
    settings = "os", "compiler"
    exports = "mylib.so"

    def package(self):
        self.copy("mylib.so", dst="lib")

    def package_info(self):
        self.cpp_info.libs = ["mylib"]
"""
        client = TestClient()
        client.save({"conanfile.py": conanfile,
                     "linux_gcc": profile,
                     "mylib.so": "fake lib content"})
        client.run("create . danimtb/testing -pr=linux_gcc")
        client.run("install MyLib/0.1@danimtb/testing -g pkg_config -pr=linux_gcc")

        pc_path = os.path.join(client.current_folder, "MyLib.pc")
        self.assertTrue(os.path.exists(pc_path))
        pc_content = load(pc_path)
        self.assertIn("-Wl,-rpath,\"${libdir}\"", pc_content)

    def test_system_libs(self):
        conanfile = """
from conans import ConanFile
from conans.tools import save
import os

class PkgConfigConan(ConanFile):
    name = "MyLib"
    version = "0.1"

    def package(self):
        save(os.path.join(self.package_folder, "lib", "file"), "")

    def package_info(self):
        self.cpp_info.libs = ["mylib1", "mylib2"]
        self.cpp_info.system_libs = ["system_lib1", "system_lib2"]
"""
        client = TestClient()
        client.save({"conanfile.py": conanfile})
        client.run("create .")
        client.run("install MyLib/0.1@ -g pkg_config")

        pc_content = client.load("MyLib.pc")
        self.assertIn('Libs: -L"${libdir}" -lmylib1  -lmylib2  -lsystem_lib1  -lsystem_lib2 ',
                      pc_content)

    def test_multiple_include(self):
        # https://github.com/conan-io/conan/issues/7056
        conanfile = textwrap.dedent("""
            from conans import ConanFile
            from conans.tools import save
            import os

            class PkgConfigConan(ConanFile):
                def package(self):
                    for p in ["inc1", "inc2", "inc3/foo", "lib1", "lib2"]:
                        save(os.path.join(self.package_folder, p, "file"), "")

                def package_info(self):
                    self.cpp_info.includedirs = ["inc1", "inc2", "inc3/foo"]
                    self.cpp_info.libdirs = ["lib1", "lib2"]
            """)
        client = TestClient()
        client.save({"conanfile.py": conanfile})
        client.run("create . pkg/0.1@")
        client.run("install pkg/0.1@ -g pkg_config")

        pc_content = client.load("pkg.pc")
        self.assertIn("includedir=${prefix}/inc1", pc_content)
        self.assertIn("includedir2=${prefix}/inc2", pc_content)
        self.assertIn("includedir3=${prefix}/inc3/foo", pc_content)
        self.assertIn("libdir=${prefix}/lib1", pc_content)
        self.assertIn("libdir2=${prefix}/lib2", pc_content)
        self.assertIn('Libs: -L"${libdir}" -L"${libdir2}"', pc_content)
        self.assertIn('Cflags: -I"${includedir}" -I"${includedir2}" -I"${includedir3}"', pc_content)

    def test_empty_include(self):
        client = TestClient()
        client.save({"conanfile.py": GenConanfile()})
        client.run("create . pkg/0.1@")
        client.run("install pkg/0.1@ -g=pkg_config")
        pc = client.load("pkg.pc")
        self.assertNotIn("libdir=${prefix}/lib", pc)
        self.assertNotIn("includedir=${prefix}/include", pc)
