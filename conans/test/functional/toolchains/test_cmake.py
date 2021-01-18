import os
import platform
import textwrap
import time
import unittest

import pytest
from parameterized.parameterized import parameterized

from conans.model.ref import ConanFileReference, PackageReference
from conans.test.assets.sources import gen_function_cpp, gen_function_h
from conans.test.functional.utils import check_vs_runtime, check_msc_ver
from conans.test.utils.tools import TestClient


@pytest.mark.toolchain
@pytest.mark.tool_cmake
class Base(unittest.TestCase):

    conanfile = textwrap.dedent("""
        from conans import ConanFile
        from conan.tools.cmake import CMake, CMakeToolchain
        class App(ConanFile):
            settings = "os", "arch", "compiler", "build_type"
            requires = "hello/0.1"
            generators = "cmake_find_package_multi"
            options = {"shared": [True, False], "fPIC": [True, False]}
            default_options = {"shared": False, "fPIC": True}

            def generate(self):
                tc = CMakeToolchain(self)
                tc.variables["MYVAR"] = "MYVAR_VALUE"
                tc.variables["MYVAR2"] = "MYVAR_VALUE2"
                tc.variables.debug["MYVAR_CONFIG"] = "MYVAR_DEBUG"
                tc.variables.release["MYVAR_CONFIG"] = "MYVAR_RELEASE"
                tc.variables.debug["MYVAR2_CONFIG"] = "MYVAR2_DEBUG"
                tc.variables.release["MYVAR2_CONFIG"] = "MYVAR2_RELEASE"
                tc.preprocessor_definitions["MYDEFINE"] = "MYDEF_VALUE"
                tc.preprocessor_definitions.debug["MYDEFINE_CONFIG"] = "MYDEF_DEBUG"
                tc.preprocessor_definitions.release["MYDEFINE_CONFIG"] = "MYDEF_RELEASE"
                tc.generate()

            def build(self):
                cmake = CMake(self)
                cmake.configure()
                cmake.build()
        """)

    lib_h = gen_function_h(name="app")
    lib_cpp = gen_function_cpp(name="app", msg="App", includes=["hello"], calls=["hello"],
                               preprocessor=["MYVAR", "MYVAR_CONFIG", "MYDEFINE", "MYDEFINE_CONFIG"])
    main = gen_function_cpp(name="main", includes=["app"], calls=["app"])

    cmakelist = textwrap.dedent("""
        cmake_minimum_required(VERSION 3.15)
        project(App C CXX)

        if(NOT CMAKE_TOOLCHAIN_FILE)
            message(FATAL ">> Not using toolchain")
        endif()
        message(">> CMAKE_GENERATOR_PLATFORM: ${CMAKE_GENERATOR_PLATFORM}")
        message(">> CMAKE_BUILD_TYPE: ${CMAKE_BUILD_TYPE}")
        message(">> CMAKE_CXX_FLAGS: ${CMAKE_CXX_FLAGS}")
        message(">> CMAKE_CXX_FLAGS_DEBUG: ${CMAKE_CXX_FLAGS_DEBUG}")
        message(">> CMAKE_CXX_FLAGS_RELEASE: ${CMAKE_CXX_FLAGS_RELEASE}")
        message(">> CMAKE_C_FLAGS: ${CMAKE_C_FLAGS}")
        message(">> CMAKE_C_FLAGS_DEBUG: ${CMAKE_C_FLAGS_DEBUG}")
        message(">> CMAKE_C_FLAGS_RELEASE: ${CMAKE_C_FLAGS_RELEASE}")
        message(">> CMAKE_SHARED_LINKER_FLAGS: ${CMAKE_SHARED_LINKER_FLAGS}")
        message(">> CMAKE_EXE_LINKER_FLAGS: ${CMAKE_EXE_LINKER_FLAGS}")
        message(">> CMAKE_CXX_STANDARD: ${CMAKE_CXX_STANDARD}")
        message(">> CMAKE_CXX_EXTENSIONS: ${CMAKE_CXX_EXTENSIONS}")
        message(">> CMAKE_POSITION_INDEPENDENT_CODE: ${CMAKE_POSITION_INDEPENDENT_CODE}")
        message(">> CMAKE_SKIP_RPATH: ${CMAKE_SKIP_RPATH}")
        message(">> CMAKE_INSTALL_NAME_DIR: ${CMAKE_INSTALL_NAME_DIR}")
        message(">> CMAKE_MODULE_PATH: ${CMAKE_MODULE_PATH}")
        message(">> CMAKE_PREFIX_PATH: ${CMAKE_PREFIX_PATH}")
        message(">> BUILD_SHARED_LIBS: ${BUILD_SHARED_LIBS}")
        get_directory_property(_COMPILE_DEFS DIRECTORY ${CMAKE_SOURCE_DIR} COMPILE_DEFINITIONS)
        message(">> COMPILE_DEFINITIONS: ${_COMPILE_DEFS}")

        find_package(hello REQUIRED)
        add_library(app_lib app_lib.cpp)
        target_link_libraries(app_lib PRIVATE hello::hello)
        target_compile_definitions(app_lib PRIVATE MYVAR="${MYVAR}")
        target_compile_definitions(app_lib PRIVATE MYVAR_CONFIG=${MYVAR_CONFIG})
        add_executable(app app.cpp)
        target_link_libraries(app PRIVATE app_lib)
        """)

    def setUp(self):
        self.client = TestClient(path_with_spaces=True)
        conanfile = textwrap.dedent("""
            from conans import ConanFile
            from conans.tools import save
            import os
            class Pkg(ConanFile):
                settings = "build_type"
                def package(self):
                    save(os.path.join(self.package_folder, "include/hello.h"),
                         '''#include <iostream>
                         void hello(){std::cout<< "Hello: %s" <<std::endl;}'''
                         % self.settings.build_type)
            """)
        self.client.save({"conanfile.py": conanfile})
        self.client.run("create . hello/0.1@ -s build_type=Debug")
        self.client.run("create . hello/0.1@ -s build_type=Release")

        # Prepare the actual consumer package
        self.client.save({"conanfile.py": self.conanfile,
                          "CMakeLists.txt": self.cmakelist,
                          "app.cpp": self.main,
                          "app_lib.cpp": self.lib_cpp,
                          "app.h": self.lib_h})

    def _run_build(self, settings=None, options=None):
        # Build the profile according to the settings provided
        settings = settings or {}
        settings = " ".join('-s %s="%s"' % (k, v) for k, v in settings.items() if v)
        options = " ".join("-o %s=%s" % (k, v) for k, v in options.items()) if options else ""

        # Run the configure corresponding to this test case
        build_directory = os.path.join(self.client.current_folder, "build").replace("\\", "/")
        with self.client.chdir(build_directory):
            self.client.run("install .. %s %s" % (settings, options))
            install_out = self.client.out
            self.client.run("build ..")
        return install_out

    def _modify_code(self):
        lib_cpp = gen_function_cpp(name="app", msg="AppImproved", includes=["hello"],
                                   calls=["hello"], preprocessor=["MYVAR", "MYVAR_CONFIG",
                                                                  "MYDEFINE", "MYDEFINE_CONFIG"])
        self.client.save({"app_lib.cpp": lib_cpp})

        content = self.client.load("CMakeLists.txt")
        content = content.replace(">>", "++>>")
        self.client.save({"CMakeLists.txt": content})

    def _incremental_build(self, build_type=None):
        build_directory = os.path.join(self.client.current_folder, "build").replace("\\", "/")
        with self.client.chdir(build_directory):
            config = "--config %s" % build_type if build_type else ""
            self.client.run_command("cmake --build . %s" % config)

    def _run_app(self, build_type, bin_folder=False, msg="App", dyld_path=None):
        if dyld_path:
            build_directory = os.path.join(self.client.current_folder, "build").replace("\\", "/")
            command_str = 'DYLD_LIBRARY_PATH="%s" build/app' % build_directory
        else:
            command_str = "build/%s/app.exe" % build_type if bin_folder else "build/app"
            if platform.system() == "Windows":
                command_str = command_str.replace("/", "\\")
        self.client.run_command(command_str)
        self.assertIn("Hello: %s" % build_type, self.client.out)
        self.assertIn("%s: %s!" % (msg, build_type), self.client.out)
        self.assertIn("MYVAR: MYVAR_VALUE", self.client.out)
        self.assertIn("MYVAR_CONFIG: MYVAR_%s" % build_type.upper(), self.client.out)
        self.assertIn("MYDEFINE: MYDEF_VALUE", self.client.out)
        self.assertIn("MYDEFINE_CONFIG: MYDEF_%s" % build_type.upper(), self.client.out)


@pytest.mark.skipif(platform.system() != "Windows", reason="Only for windows")
class WinTest(Base):
    @parameterized.expand([("Visual Studio", "Debug", "MTd", "15", "14", "x86", "v140", True),
                           ("Visual Studio", "Release", "MD", "15", "17", "x86_64", "", False),
                           ("msvc", "Debug", "static", "19.1", "14", "x86", None, True),
                           ("msvc", "Release", "dynamic", "19.11", "17", "x86_64", None, False)]
                          )
    def test_toolchain_win(self, compiler, build_type, runtime, version, cppstd, arch, toolset,
                           shared):
        settings = {"compiler": compiler,
                    "compiler.version": version,
                    "compiler.toolset": toolset,
                    "compiler.runtime": runtime,
                    "compiler.cppstd": cppstd,
                    "arch": arch,
                    "build_type": build_type,
                    }
        options = {"shared": shared}
        install_out = self._run_build(settings, options)
        self.assertIn("WARN: Toolchain: Ignoring fPIC option defined for Windows", install_out)

        # FIXME: Hardcoded VS version and partial toolset check
        self.assertIn('CMake command: cmake -G "Visual Studio 15 2017" '
                      '-DCMAKE_TOOLCHAIN_FILE="conan_toolchain.cmake"', self.client.out)
        if toolset == "v140":
            self.assertIn("Microsoft Visual Studio 14.0", self.client.out)
        else:
            self.assertIn("Microsoft Visual Studio/2017", self.client.out)

        generator_platform = "x64" if arch == "x86_64" else "Win32"
        arch = "x64" if arch == "x86_64" else "X86"
        shared_str = "ON" if shared else "OFF"
        vals = {"CMAKE_GENERATOR_PLATFORM": generator_platform,
                "CMAKE_BUILD_TYPE": "",
                "CMAKE_CXX_FLAGS": "/MP1 /DWIN32 /D_WINDOWS /GR /EHsc",
                "CMAKE_CXX_FLAGS_DEBUG": "/Zi /Ob0 /Od /RTC1",
                "CMAKE_CXX_FLAGS_RELEASE": "/O2 /Ob2 /DNDEBUG",
                "CMAKE_C_FLAGS": "/MP1 /DWIN32 /D_WINDOWS",
                "CMAKE_C_FLAGS_DEBUG": "/Zi /Ob0 /Od /RTC1",
                "CMAKE_C_FLAGS_RELEASE": "/O2 /Ob2 /DNDEBUG",
                "CMAKE_SHARED_LINKER_FLAGS": "/machine:%s" % arch,
                "CMAKE_EXE_LINKER_FLAGS": "/machine:%s" % arch,
                "CMAKE_CXX_STANDARD": cppstd,
                "CMAKE_CXX_EXTENSIONS": "OFF",
                "BUILD_SHARED_LIBS": shared_str}

        def _verify_out(marker=">>"):
            if shared:
                self.assertIn("app_lib.dll", self.client.out)
            else:
                self.assertNotIn("app_lib.dll", self.client.out)

            out = str(self.client.out).splitlines()
            for k, v in vals.items():
                self.assertIn("%s %s: %s" % (marker, k, v), out)

        _verify_out()

        opposite_build_type = "Release" if build_type == "Debug" else "Debug"
        settings["build_type"] = opposite_build_type
        if runtime == "MTd":
            settings["compiler.runtime"] = "MT"
        if runtime == "MD":
            settings["compiler.runtime"] = "MDd"
        self._run_build(settings, options)

        self._run_app("Release", bin_folder=True)
        check_msc_ver(toolset or "v141", self.client.out)
        self.assertIn("main _MSVC_LANG20{}".format(cppstd), self.client.out)
        self._run_app("Debug", bin_folder=True)
        check_msc_ver(toolset or "v141", self.client.out)
        self.assertIn("main _MSVC_LANG20{}".format(cppstd), self.client.out)
        static = (runtime == "static" or "MT" in runtime)
        check_vs_runtime("build/Release/app.exe", self.client, "15", build_type="Release",
                         static=static)
        check_vs_runtime("build/Debug/app.exe", self.client, "15", build_type="Debug",
                         static=static)

        self._modify_code()
        time.sleep(1)
        self._incremental_build(build_type=build_type)
        _verify_out(marker="++>>")
        self._run_app(build_type, bin_folder=True, msg="AppImproved")
        self._incremental_build(build_type=opposite_build_type)
        self._run_app(opposite_build_type, bin_folder=True, msg="AppImproved")

    @parameterized.expand([("Debug", "libstdc++", "4.9", "98", "x86_64", True),
                           ("Release", "libstdc++", "4.9", "11", "x86_64", False)])
    def test_toolchain_mingw_win(self, build_type, libcxx, version, cppstd, arch, shared):
        settings = {"compiler": "gcc",
                    "compiler.version": version,
                    "compiler.libcxx": libcxx,
                    "compiler.cppstd": cppstd,
                    "arch": arch,
                    "build_type": build_type,
                    }
        options = {"shared": shared}
        install_out = self._run_build(settings, options)
        self.assertIn("WARN: Toolchain: Ignoring fPIC option defined for Windows", install_out)
        self.assertIn("The C compiler identification is GNU", self.client.out)
        self.assertIn('CMake command: cmake -G "MinGW Makefiles" '
                      '-DCMAKE_TOOLCHAIN_FILE="conan_toolchain.cmake"', self.client.out)

        def _verify_out(marker=">>"):
            cmake_vars = {"CMAKE_GENERATOR_PLATFORM": "",
                          "CMAKE_BUILD_TYPE": build_type,
                          "CMAKE_CXX_FLAGS": "-m64",
                          "CMAKE_CXX_FLAGS_DEBUG": "-g",
                          "CMAKE_CXX_FLAGS_RELEASE": "-O3 -DNDEBUG",
                          "CMAKE_C_FLAGS": "-m64",
                          "CMAKE_C_FLAGS_DEBUG": "-g",
                          "CMAKE_C_FLAGS_RELEASE": "-O3 -DNDEBUG",
                          "CMAKE_SHARED_LINKER_FLAGS": "-m64",
                          "CMAKE_EXE_LINKER_FLAGS": "-m64",
                          "CMAKE_CXX_STANDARD": cppstd,
                          "CMAKE_CXX_EXTENSIONS": "OFF",
                          "BUILD_SHARED_LIBS": "ON" if shared else "OFF"}
            if shared:
                self.assertIn("app_lib.dll", self.client.out)
            else:
                self.assertNotIn("app_lib.dll", self.client.out)

            out = str(self.client.out).splitlines()
            for k, v in cmake_vars.items():
                self.assertIn("%s %s: %s" % (marker, k, v), out)

        _verify_out()
        self._run_app(build_type)

        self._modify_code()
        time.sleep(2)
        self._incremental_build()
        _verify_out(marker="++>>")
        self._run_app(build_type, msg="AppImproved")


@pytest.mark.skipif(platform.system() != "Linux", reason="Only for Linux")
class LinuxTest(Base):
    @parameterized.expand([("Debug",  "14", "x86", "libstdc++", True),
                           ("Release", "gnu14", "x86_64", "libstdc++11", False)])
    def test_toolchain_linux(self, build_type, cppstd, arch, libcxx, shared):
        settings = {"compiler": "gcc",
                    "compiler.cppstd": cppstd,
                    "compiler.libcxx": libcxx,
                    "arch": arch,
                    "build_type": build_type}
        self._run_build(settings, {"shared": shared})

        self.assertIn('CMake command: cmake -G "Unix Makefiles" '
                      '-DCMAKE_TOOLCHAIN_FILE="conan_toolchain.cmake"', self.client.out)

        extensions_str = "ON" if "gnu" in cppstd else "OFF"
        pic_str = "" if shared else "ON"
        arch_str = "-m32" if arch == "x86" else "-m64"
        cxx11_abi_str = "1" if libcxx == "libstdc++11" else "0"
        defines = '_GLIBCXX_USE_CXX11_ABI=%s;MYDEFINE="MYDEF_VALUE";'\
                  'MYDEFINE_CONFIG=$<IF:$<CONFIG:debug>,"MYDEF_DEBUG",'\
                  '$<IF:$<CONFIG:release>,"MYDEF_RELEASE","">>' % cxx11_abi_str
        vals = {"CMAKE_CXX_STANDARD": "14",
                "CMAKE_CXX_EXTENSIONS": extensions_str,
                "CMAKE_BUILD_TYPE": build_type,
                "CMAKE_CXX_FLAGS": arch_str,
                "CMAKE_CXX_FLAGS_DEBUG": "-g",
                "CMAKE_CXX_FLAGS_RELEASE": "-O3 -DNDEBUG",
                "CMAKE_C_FLAGS": arch_str,
                "CMAKE_C_FLAGS_DEBUG": "-g",
                "CMAKE_C_FLAGS_RELEASE": "-O3 -DNDEBUG",
                "CMAKE_SHARED_LINKER_FLAGS": arch_str,
                "CMAKE_EXE_LINKER_FLAGS": arch_str,
                "COMPILE_DEFINITIONS": defines,
                "CMAKE_POSITION_INDEPENDENT_CODE": pic_str
                }

        def _verify_out(marker=">>"):
            if shared:
                self.assertIn("libapp_lib.so", self.client.out)
            else:
                self.assertIn("libapp_lib.a", self.client.out)

            out = str(self.client.out).splitlines()
            for k, v in vals.items():
                self.assertIn("%s %s: %s" % (marker, k, v), out)

        _verify_out()

        self._run_app(build_type)

        self._modify_code()
        self._incremental_build()
        _verify_out(marker="++>>")
        self._run_app(build_type, msg="AppImproved")


@pytest.mark.skipif(platform.system() != "Darwin", reason="Only for Apple")
class AppleTest(Base):
    @parameterized.expand([("Debug",  "14",  True),
                           ("Release", "", False)])
    def test_toolchain_apple(self, build_type, cppstd, shared):
        settings = {"compiler": "apple-clang",
                    "compiler.cppstd": cppstd,
                    "build_type": build_type}
        self._run_build(settings, {"shared": shared})

        self.assertIn('CMake command: cmake -G "Unix Makefiles" '
                      '-DCMAKE_TOOLCHAIN_FILE="conan_toolchain.cmake"', self.client.out)

        extensions_str = "OFF" if cppstd else ""
        vals = {"CMAKE_CXX_STANDARD": cppstd,
                "CMAKE_CXX_EXTENSIONS": extensions_str,
                "CMAKE_BUILD_TYPE": build_type,
                "CMAKE_CXX_FLAGS": "-m64 -stdlib=libc++",
                "CMAKE_CXX_FLAGS_DEBUG": "-g",
                "CMAKE_CXX_FLAGS_RELEASE": "-O3 -DNDEBUG",
                "CMAKE_C_FLAGS": "-m64",
                "CMAKE_C_FLAGS_DEBUG": "-g",
                "CMAKE_C_FLAGS_RELEASE": "-O3 -DNDEBUG",
                "CMAKE_SHARED_LINKER_FLAGS": "-m64",
                "CMAKE_EXE_LINKER_FLAGS": "-m64",
                "CMAKE_SKIP_RPATH": "1",
                "CMAKE_INSTALL_NAME_DIR": ""
                }

        def _verify_out(marker=">>"):
            if shared:
                self.assertIn("libapp_lib.dylib", self.client.out)
            else:
                if marker == ">>":
                    self.assertIn("libapp_lib.a", self.client.out)
                else:  # Incremental build not the same msg
                    self.assertIn("Built target app_lib", self.client.out)
            out = str(self.client.out).splitlines()
            for k, v in vals.items():
                self.assertIn("%s %s: %s" % (marker, k, v), out)

        _verify_out()

        self._run_app(build_type, dyld_path=shared)

        self._modify_code()
        time.sleep(1)
        self._incremental_build()
        _verify_out(marker="++>>")
        self._run_app(build_type, dyld_path=shared, msg="AppImproved")


@pytest.mark.toolchain
@pytest.mark.tool_cmake
class CMakeInstallTest(unittest.TestCase):

    def test_install(self):
        conanfile = textwrap.dedent("""
            from conans import ConanFile
            from conan.tools.cmake import CMake, CMakeToolchain
            class App(ConanFile):
                settings = "os", "arch", "compiler", "build_type"
                exports_sources = "CMakeLists.txt", "header.h"
                def generate(self):
                    tc = CMakeToolchain(self)
                    tc.generate()
                def build(self):
                    cmake = CMake(self)
                    cmake.configure()
                def package(self):
                    cmake = CMake(self)
                    cmake.install()
            """)

        cmakelist = textwrap.dedent("""
            cmake_minimum_required(VERSION 2.8)
            project(App C)
            if(CONAN_TOOLCHAIN_INCLUDED AND CMAKE_VERSION VERSION_LESS "3.15")
                include("${CMAKE_BINARY_DIR}/conan_project_include.cmake")
            endif()
            if(NOT CMAKE_TOOLCHAIN_FILE)
                message(FATAL ">> Not using toolchain")
            endif()
            install(FILES header.h DESTINATION include)
            """)
        client = TestClient(path_with_spaces=False)
        client.save({"conanfile.py": conanfile,
                     "CMakeLists.txt": cmakelist,
                     "header.h": "# my header file"})

        # FIXME: This is broken, because the toolchain at install time, doesn't have the package
        # folder yet. We need to define the layout for local development
        """
        with client.chdir("build"):
            client.run("install ..")
            client.run("build ..")
            client.run("package .. -pf=mypkg")  # -pf=mypkg ignored
        self.assertTrue(os.path.exists(os.path.join(client.current_folder, "build",
                                                    "include", "header.h")))"""

        # The create flow must work
        client.run("create . pkg/0.1@")
        self.assertIn("pkg/0.1 package(): Packaged 1 '.h' file: header.h", client.out)
        ref = ConanFileReference.loads("pkg/0.1")
        layout = client.cache.package_layout(ref)
        package_id = layout.package_ids()[0]
        package_folder = layout.package(PackageReference(ref, package_id))
        self.assertTrue(os.path.exists(os.path.join(package_folder, "include", "header.h")))


@pytest.mark.toolchain
@pytest.mark.tool_cmake
class CMakeOverrideCacheTest(unittest.TestCase):

    def test_cmake_cache_variables(self):
        # https://github.com/conan-io/conan/issues/7832
        conanfile = textwrap.dedent("""
            from conans import ConanFile
            from conan.tools.cmake import CMake, CMakeToolchain
            class App(ConanFile):
                settings = "os", "arch", "compiler", "build_type"
                exports_sources = "CMakeLists.txt"
                def generate(self):
                    toolchain = CMakeToolchain(self)
                    toolchain.variables["my_config_string"] = "my new value"
                    toolchain.generate()
                def build(self):
                    cmake = CMake(self)
                    cmake.configure()
            """)

        cmakelist = textwrap.dedent("""
            cmake_minimum_required(VERSION 3.7)
            project(my_project)
            set(my_config_string "default value" CACHE STRING "my config string")
            message(STATUS "VALUE OF CONFIG STRING: ${my_config_string}")
            """)
        client = TestClient()
        client.save({"conanfile.py": conanfile,
                     "CMakeLists.txt": cmakelist})
        client.run("install .")
        client.run("build .")
        self.assertIn("VALUE OF CONFIG STRING: my new value", client.out)
