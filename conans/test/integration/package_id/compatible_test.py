import textwrap
import time
import unittest

from conans.model.ref import ConanFileReference
from conans.test.utils.tools import TestClient, GenConanfile


class CompatibleIDsTest(unittest.TestCase):

    def test_compatible_setting(self):
        client = TestClient()
        conanfile = textwrap.dedent("""
            from conans import ConanFile

            class Pkg(ConanFile):
                settings = "os", "compiler"
                def package_id(self):
                    if self.settings.compiler == "gcc" and self.settings.compiler.version == "4.9":
                        for version in ("4.8", "4.7", "4.6"):
                            compatible_pkg = self.info.clone()
                            compatible_pkg.settings.compiler.version = version
                            self.compatible_packages.append(compatible_pkg)
                def package_info(self):
                    self.output.info("PackageInfo!: Gcc version: %s!"
                                     % self.settings.compiler.version)
            """)
        profile = textwrap.dedent("""
            [settings]
            os = Linux
            compiler=gcc
            compiler.version=4.9
            compiler.libcxx=libstdc++
            """)
        client.save({"conanfile.py": conanfile,
                     "myprofile": profile})
        # Create package with gcc 4.8
        client.run("create . pkg/0.1@user/stable -pr=myprofile -s compiler.version=4.8")
        self.assertIn("pkg/0.1@user/stable: Package '22c594d7fed4994c59a1eacb24ff6ff48bc5c51c'"
                      " created", client.out)

        # package can be used with a profile gcc 4.9 falling back to 4.8 binary
        client.save({"conanfile.py": GenConanfile().with_require("pkg/0.1@user/stable")})
        client.run("install . -pr=myprofile")
        self.assertIn("pkg/0.1@user/stable: PackageInfo!: Gcc version: 4.8!", client.out)
        self.assertIn("pkg/0.1@user/stable:22c594d7fed4994c59a1eacb24ff6ff48bc5c51c", client.out)
        self.assertIn("pkg/0.1@user/stable: Already installed!", client.out)

    def test_compatible_setting_no_binary(self):
        client = TestClient()
        conanfile = textwrap.dedent("""
           from conans import ConanFile

           class Pkg(ConanFile):
               settings = "os", "compiler"
               def package_id(self):
                   if self.settings.compiler == "gcc" and self.settings.compiler.version == "4.9":
                       for version in ("4.8", "4.7", "4.6"):
                           compatible_pkg = self.info.clone()
                           compatible_pkg.settings.compiler.version = version
                           self.compatible_packages.append(compatible_pkg)
               def package_info(self):
                   self.output.info("PackageInfo!: Gcc version: %s!"
                                    % self.settings.compiler.version)
           """)
        profile = textwrap.dedent("""
           [settings]
           os = Linux
           compiler=gcc
           compiler.version=4.9
           compiler.libcxx=libstdc++
           """)
        client.save({"conanfile.py": conanfile,
                     "myprofile": profile})
        # Create package with gcc 4.8
        client.run("export . pkg/0.1@user/stable")
        self.assertIn("pkg/0.1@user/stable: Exported revision: b27c975bb0d9e40c328bd02bc529b6f8",
                      client.out)

        # package can be used with a profile gcc 4.9 falling back to 4.8 binary
        client.save({"conanfile.py": GenConanfile().with_require("pkg/0.1@user/stable")})
        # No fallback
        client.run("install . -pr=myprofile --build=missing")
        self.assertIn("pkg/0.1@user/stable: PackageInfo!: Gcc version: 4.9!", client.out)
        self.assertIn("pkg/0.1@user/stable:53f56fbd582a1898b3b9d16efd6d3c0ec71e7cfb - Build",
                      client.out)

    def test_compatible_setting_no_user_channel(self):
        client = TestClient()
        conanfile = textwrap.dedent("""
            from conans import ConanFile

            class Pkg(ConanFile):
                settings = "os", "compiler"
                def package_id(self):
                    if self.settings.compiler == "gcc" and self.settings.compiler.version == "4.9":
                        for version in ("4.8", "4.7", "4.6"):
                            compatible_pkg = self.info.clone()
                            compatible_pkg.settings.compiler.version = version
                            self.compatible_packages.append(compatible_pkg)
            """)
        profile = textwrap.dedent("""
            [settings]
            os = Linux
            compiler=gcc
            compiler.version=4.9
            compiler.libcxx=libstdc++
            """)
        client.save({"conanfile.py": conanfile,
                     "myprofile": profile})

        # No user/channel
        client.run("create . pkg/0.1@ -pr=myprofile -s compiler.version=4.8")
        self.assertIn("pkg/0.1: Package '22c594d7fed4994c59a1eacb24ff6ff48bc5c51c' created",
                      client.out)

        client.save({"conanfile.py": GenConanfile().with_require("pkg/0.1")})
        client.run("install . -pr=myprofile")
        self.assertIn("pkg/0.1:22c594d7fed4994c59a1eacb24ff6ff48bc5c51c", client.out)
        self.assertIn("pkg/0.1: Already installed!", client.out)

    def test_compatible_option(self):
        client = TestClient()
        conanfile = textwrap.dedent("""
            from conans import ConanFile

            class Pkg(ConanFile):
                options = {"optimized": [1, 2, 3]}
                default_options = {"optimized": 1}
                def package_id(self):
                    for optimized in range(int(self.options.optimized), 0, -1):
                        compatible_pkg = self.info.clone()
                        compatible_pkg.options.optimized = optimized
                        self.compatible_packages.append(compatible_pkg)
                def package_info(self):
                    self.output.info("PackageInfo!: Option optimized %s!"
                                     % self.options.optimized)
            """)
        client.save({"conanfile.py": conanfile})
        client.run("create . pkg/0.1@user/stable")
        self.assertIn("pkg/0.1@user/stable: Package 'a97db2488658dd582a070ba8b6c6975eb1601a33'"
                      " created", client.out)

        client.save({"conanfile.py": GenConanfile().with_require("pkg/0.1@user/stable")})
        client.run("install . -o pkg:optimized=2")
        # Information messages
        self.assertIn("pkg/0.1@user/stable: PackageInfo!: Option optimized 1!", client.out)
        self.assertIn("pkg/0.1@user/stable: Compatible package ID "
                      "d97fb97a840e4ac3b5e7bb8f79c87f1d333a85bc equal to the default package ID",
                      client.out)
        self.assertIn("pkg/0.1@user/stable: Main binary package "
                      "'d97fb97a840e4ac3b5e7bb8f79c87f1d333a85bc' missing. Using compatible package"
                      " 'a97db2488658dd582a070ba8b6c6975eb1601a33'", client.out)
        # checking the resulting dependencies
        self.assertIn("pkg/0.1@user/stable:a97db2488658dd582a070ba8b6c6975eb1601a33 - Cache",
                      client.out)
        self.assertIn("pkg/0.1@user/stable: Already installed!", client.out)
        client.run("install . -o pkg:optimized=3")
        self.assertIn("pkg/0.1@user/stable:a97db2488658dd582a070ba8b6c6975eb1601a33 - Cache",
                      client.out)
        self.assertIn("pkg/0.1@user/stable: Already installed!", client.out)

    def test_visual_package_compatible_with_intel(self):
        client = TestClient()
        ref = ConanFileReference.loads("Bye/0.1@us/ch")
        conanfile = textwrap.dedent("""
        from conans import ConanFile

        class Conan(ConanFile):
            settings = "compiler"

            def package_id(self):
                if self.settings.compiler == "intel":
                    p = self.info.clone()
                    p.base_compatible()
                    self.compatible_packages.append(p)
            """)
        visual_profile = textwrap.dedent("""
            [settings]
            compiler = Visual Studio
            compiler.version = 8
            compiler.runtime = MD
            """)
        intel_profile = textwrap.dedent("""
            [settings]
            compiler = intel
            compiler.version = 16
            compiler.base = Visual Studio
            compiler.base.version = 8
            compiler.base.runtime = MD
            """)
        client.save({"conanfile.py": conanfile,
                     "intel_profile": intel_profile,
                     "visual_profile": visual_profile})
        client.run("create . %s --profile visual_profile" % ref.full_str())
        client.run("install %s -pr intel_profile" % ref.full_str())
        self.assertIn("Bye/0.1@us/ch: Main binary package '2ef6f6c768dd0f332dc252"
                      "b72c30dee116632302' missing. Using compatible package "
                      "'1151fe341e6b310f7645a76b4d3d524342835acc'",
                      client.out)
        self.assertIn("Bye/0.1@us/ch:1151fe341e6b310f7645a76b4d3d524342835acc - Cache", client.out)

    def test_wrong_base_compatible(self):
        client = TestClient()
        ref = ConanFileReference.loads("Bye/0.1@us/ch")
        conanfile = textwrap.dedent("""
        from conans import ConanFile

        class Conan(ConanFile):
            settings = "compiler"

            def package_id(self):
                p = self.info.clone()
                p.base_compatible()
                self.compatible_packages.append(p)
            """)
        visual_profile = textwrap.dedent("""
            [settings]
            compiler = Visual Studio
            compiler.version = 8
            compiler.runtime = MD
            """)
        client.save({"conanfile.py": conanfile,
                     "visual_profile": visual_profile})
        client.run("create . %s --profile visual_profile" % ref.full_str(), assert_error=True)
        self.assertIn("The compiler 'Visual Studio' has no 'base' sub-setting", client.out)

    def test_intel_package_compatible_with_base(self):
        client = TestClient()
        ref = ConanFileReference.loads("Bye/0.1@us/ch")
        conanfile = textwrap.dedent("""
        from conans import ConanFile

        class Conan(ConanFile):
            settings = "compiler"

            def package_id(self):
               if self.settings.compiler == "Visual Studio":
                   compatible_pkg = self.info.clone()
                   compatible_pkg.parent_compatible(compiler="intel", version=16)
                   self.compatible_packages.append(compatible_pkg)

            """)
        visual_profile = textwrap.dedent("""
            [settings]
            compiler = Visual Studio
            compiler.version = 8
            compiler.runtime = MD
            """)
        intel_profile = textwrap.dedent("""
            [settings]
            compiler = intel
            compiler.version = 16
            compiler.base = Visual Studio
            compiler.base.version = 8
            compiler.base.runtime = MD
            """)
        client.save({"conanfile.py": conanfile,
                     "intel_profile": intel_profile,
                     "visual_profile": visual_profile})
        client.run("create . %s --profile intel_profile" % ref.full_str())
        client.run("install %s -pr visual_profile" % ref.full_str())
        self.assertIn("Bye/0.1@us/ch: Main binary package "
                      "'1151fe341e6b310f7645a76b4d3d524342835acc' missing. Using compatible "
                      "package '2ef6f6c768dd0f332dc252b72c30dee116632302'",
                      client.out)
        self.assertIn("Bye/0.1@us/ch:2ef6f6c768dd0f332dc252b72c30dee116632302 - Cache", client.out)

    def test_no_valid_compiler_keyword_base(self):
        client = TestClient()
        ref = ConanFileReference.loads("Bye/0.1@us/ch")
        conanfile = textwrap.dedent("""
        from conans import ConanFile

        class Conan(ConanFile):
            settings = "compiler"

            def package_id(self):
               if self.settings.compiler == "Visual Studio":
                   compatible_pkg = self.info.clone()
                   compatible_pkg.parent_compatible("intel")
                   self.compatible_packages.append(compatible_pkg)

            """)
        visual_profile = textwrap.dedent("""
            [settings]
            compiler = Visual Studio
            compiler.version = 8
            compiler.runtime = MD
            """)
        client.save({"conanfile.py": conanfile,
                     "visual_profile": visual_profile})
        client.run("create . %s --profile visual_profile" % ref.full_str(), assert_error=True)
        self.assertIn("Specify 'compiler' as a keywork "
                      "argument. e.g: 'parent_compiler(compiler=\"intel\")'", client.out)

    def test_intel_package_invalid_subsetting(self):
        """If I specify an invalid subsetting of my base compiler, it won't fail, but it won't
        file the available package_id"""
        client = TestClient()
        ref = ConanFileReference.loads("Bye/0.1@us/ch")
        conanfile = textwrap.dedent("""
            from conans import ConanFile

            class Conan(ConanFile):
                settings = "compiler"

                def package_id(self):
                   if self.settings.compiler == "Visual Studio":
                       compatible_pkg = self.info.clone()
                       compatible_pkg.parent_compatible(compiler="intel", version=16, FOO="BAR")
                       self.compatible_packages.append(compatible_pkg)
            """)
        visual_profile = textwrap.dedent("""
            [settings]
            compiler = Visual Studio
            compiler.version = 8
            compiler.runtime = MD
            """)
        intel_profile = textwrap.dedent("""
            [settings]
            compiler = intel
            compiler.version = 16
            compiler.base = Visual Studio
            compiler.base.version = 8
            compiler.base.runtime = MD
            """)
        client.save({"conanfile.py": conanfile,
                     "intel_profile": intel_profile,
                     "visual_profile": visual_profile})
        client.run("create . %s --profile intel_profile" % ref.full_str())
        client.run("install %s -pr visual_profile" % ref.full_str(), assert_error=True)
        self.assertIn("Missing prebuilt package for 'Bye/0.1@us/ch'", client.out)

    def test_additional_id_mode(self):
        c1 = GenConanfile().with_name("AA").with_version("1.0")
        c2 = GenConanfile().with_name("BB").with_version("1.0").with_require("AA/1.0")
        client = TestClient()
        # Recipe revision mode
        client.run("config set general.default_package_id_mode=recipe_revision_mode")

        # Create binaries with recipe revision mode for both
        client.save({"conanfile.py": c1})
        client.run("create .")

        client.save({"conanfile.py": c2})
        client.run("create .")

        # Back to semver default
        client.run("config set general.default_package_id_mode=semver_direct_mode")
        client.run("install BB/1.0@", assert_error=True)
        self.assertIn("Missing prebuilt package for 'BB/1.0'", client.out)

        # What if client modifies the packages declaring a compatible_package with the recipe mode
        # Recipe revision mode
        client.run("config set general.default_package_id_mode=recipe_revision_mode")
        tmp = """

    def package_id(self):
        p = self.info.clone()
        p.requires.recipe_revision_mode()
        self.output.warn("Alternative package ID: {}".format(p.package_id()))
        self.compatible_packages.append(p)
"""
        c1 = str(c1) + tmp
        c2 = str(c2) + tmp
        # Create the packages, now with the recipe mode declared as compatible package
        time.sleep(1)  # new timestamp
        client.save({"conanfile.py": c1})
        client.run("create .")

        client.save({"conanfile.py": c2})
        client.run("create .")
        self.assertIn("Package 'ce6719c914d00372f1a2ae66543c0d135a684951' created", client.out)

        # Back to semver mode
        client.run("config set general.default_package_id_mode=semver_direct_mode")
        client.run("install BB/1.0@ --update")
        self.assertIn("Using compatible package 'ce6719c914d00372f1a2ae66543c0d135a684951'",
                      client.out)

    def test_package_id_consumers(self):
        # If we fallback to a different binary upstream and we are using a "package_revision_mode"
        # the current package should have a different binary package ID too.
        client = TestClient()
        client.run("config set general.default_package_id_mode=package_revision_mode")
        conanfile = textwrap.dedent("""
            from conans import ConanFile
            class Pkg(ConanFile):
                settings = "os", "compiler"
                def package_id(self):
                    compatible = self.info.clone()
                    compatible.settings.compiler.version = "4.8"
                    self.compatible_packages.append(compatible)
                def package_info(self):
                    self.output.info("PackageInfo!: Gcc version: %s!"
                                     % self.settings.compiler.version)
            """)
        profile = textwrap.dedent("""
            [settings]
            os = Linux
            compiler=gcc
            compiler.version=4.9
            compiler.libcxx=libstdc++
            """)
        client.save({"conanfile.py": conanfile,
                     "myprofile": profile})
        # Create package with gcc 4.8
        client.run("create . pkg/0.1@user/stable -pr=myprofile -s compiler.version=4.8")
        self.assertIn("pkg/0.1@user/stable: Package '22c594d7fed4994c59a1eacb24ff6ff48bc5c51c'"
                      " created", client.out)

        # package can be used with a profile gcc 4.9 falling back to 4.8 binary
        client.save({"conanfile.py": GenConanfile().with_require("pkg/0.1@user/stable")})
        client.run("create . consumer/0.1@user/stable -pr=myprofile")
        self.assertIn("pkg/0.1@user/stable: PackageInfo!: Gcc version: 4.8!", client.out)
        self.assertIn("pkg/0.1@user/stable:22c594d7fed4994c59a1eacb24ff6ff48bc5c51c - Cache",
                      client.out)
        self.assertIn("pkg/0.1@user/stable: Already installed!", client.out)
        self.assertIn("consumer/0.1@user/stable:15c77f209e7dca571ffe63b19a04a634654e4211 - Build",
                      client.out)
        self.assertIn("consumer/0.1@user/stable: Package '15c77f209e7dca571ffe63b19a04a634654e4211'"
                      " created", client.out)

        # Create package with gcc 4.9
        client.save({"conanfile.py": conanfile})
        client.run("create . pkg/0.1@user/stable -pr=myprofile")
        self.assertIn("pkg/0.1@user/stable: Package '53f56fbd582a1898b3b9d16efd6d3c0ec71e7cfb'"
                      " created", client.out)

        # Consume it
        client.save({"conanfile.py": GenConanfile().with_require("pkg/0.1@user/stable")})
        client.run("create . consumer/0.1@user/stable -pr=myprofile")
        self.assertIn("pkg/0.1@user/stable: PackageInfo!: Gcc version: 4.9!", client.out)
        self.assertIn("pkg/0.1@user/stable:53f56fbd582a1898b3b9d16efd6d3c0ec71e7cfb - Cache",
                      client.out)
        self.assertIn("pkg/0.1@user/stable: Already installed!", client.out)
        self.assertIn("consumer/0.1@user/stable:fca9e94084ed6fe0ca149dc9c2d54c0f336f0d7e - Build",
                      client.out)
        self.assertIn("consumer/0.1@user/stable: Package 'fca9e94084ed6fe0ca149dc9c2d54c0f336f0d7e'"
                      " created", client.out)

    def test_build_missing(self):
        # https://github.com/conan-io/conan/issues/6133
        client = TestClient()
        conanfile = textwrap.dedent("""
            from conans import ConanFile

            class Conan(ConanFile):
                settings = "os"

                def package_id(self):
                   if self.settings.os == "Windows":
                       compatible = self.info.clone()
                       compatible.settings.os = "Linux"
                       self.compatible_packages.append(compatible)
                """)

        client.save({"conanfile.py": conanfile})
        client.run("create . pkg/0.1@user/testing -s os=Linux")

        client.save({"conanfile.py": GenConanfile().with_require("pkg/0.1@user/testing")})
        client.run("install . -s os=Windows --build=missing")
        self.assertIn("pkg/0.1@user/testing:cb054d0b3e1ca595dc66bc2339d40f1f8f04ab31 - Cache",
                      client.out)
        self.assertIn("pkg/0.1@user/testing: Already installed!", client.out)

    def test_compatible_package_python_requires(self):
        # https://github.com/conan-io/conan/issues/6609
        client = TestClient()
        client.save({"conanfile.py": GenConanfile()})
        client.run("export . tool/0.1@")
        conanfile = textwrap.dedent("""
            from conans import ConanFile

            class Conan(ConanFile):
                settings = "os"
                python_requires = "tool/0.1"

                def package_id(self):
                   if self.settings.os == "Windows":
                       compatible = self.info.clone()
                       compatible.settings.os = "Linux"
                       self.compatible_packages.append(compatible)
                """)

        client.save({"conanfile.py": conanfile})
        client.run("create . pkg/0.1@user/testing -s os=Linux")

        client.save({"conanfile.py": GenConanfile().with_require("pkg/0.1@user/testing")})
        client.run("install . -s os=Windows")
        self.assertIn("pkg/0.1@user/testing:1ebf4db7209535776307f9cd06e00d5a8034bc84 - Cache",
                      client.out)
        self.assertIn("pkg/0.1@user/testing: Already installed!", client.out)


def test_msvc_visual_incompatible():
    conanfile = GenConanfile().with_settings("os", "compiler", "build_type", "arch")
    client = TestClient()
    client.save({"conanfile.py": conanfile})
    client.run('create . pkg/0.1@ -s os=Windows -s compiler="Visual Studio" -s compiler.version=15 '
               '-s compiler.runtime=MD -s build_type=Release -s arch=x86_64')
    client.run("install pkg/0.1@  -s os=Windows -s compiler=msvc -s compiler.version=19.1 "
               "-s compiler.runtime=dynamic -s build_type=Release -s arch=x86_64 "
               "-s compiler.cppstd=14")
    assert "Using compatible package" in client.out
    client.run("config set general.msvc_visual_incompatible=1")
    client.run("install pkg/0.1@  -s os=Windows -s compiler=msvc -s compiler.version=19.1 "
               "-s compiler.runtime=dynamic -s build_type=Release -s arch=x86_64 "
               "-s compiler.cppstd=14", assert_error=True)
    assert "ERROR: Missing prebuilt package for 'pkg/0.1'" in client.out
