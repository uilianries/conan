import os
import textwrap
import unittest

from parameterized.parameterized import parameterized

from conans.model.ref import ConanFileReference
from conans.paths import CONANFILE
from conans.test.utils.tools import TestClient, GenConanfile
from conans.util.files import load
from conans.test.utils.conanfile import TestConanFile

tool_conanfile = """from conans import ConanFile

class Tool(ConanFile):
    name = "Tool"
    version = "0.1"

    def package_info(self):
        self.env_info.TOOL_PATH.append("MyToolPath")
"""

tool_conanfile2 = tool_conanfile.replace("0.1", "0.3")

conanfile = """
import os
from conans import ConanFile, tools

class MyLib(ConanFile):
    name = "MyLib"
    version = "0.1"
    {}

    def build(self):
        self.output.info("ToolPath: %s" % os.getenv("TOOL_PATH"))
"""

requires = conanfile.format('build_requires = "Tool/0.1@lasote/stable"')
requires_range = conanfile.format('build_requires = "Tool/[>0.0]@lasote/stable"')
requirements = conanfile.format("""def build_requirements(self):
        self.build_requires("Tool/0.1@lasote/stable")""")
override = conanfile.format("""build_requires = "Tool/0.2@user/channel"

    def build_requirements(self):
        self.build_requires("Tool/0.1@lasote/stable")""")


profile = """
[build_requires]
Tool/0.3@lasote/stable
nonexistingpattern*: SomeTool/1.2@user/channel
"""


class BuildRequiresTest(unittest.TestCase):

    def test_consumer(self):
        # https://github.com/conan-io/conan/issues/5425
        t = TestClient()
        t.save({"conanfile.py": str(TestConanFile("catch", "0.1", info=True))})
        t.run("create . catch/0.1@user/testing")
        t.save({"conanfile.py": str(TestConanFile("LibA", "0.1",
                                                  private_requires=["catch/0.1@user/testing"]))})
        t.run("create . LibA/0.1@user/testing")
        t.save({"conanfile.py": str(TestConanFile("LibC", "0.1",
                                                  requires=["LibA/0.1@user/testing"],
                                                  build_requires=["catch/0.1@user/testing"]))})
        t.run("install .")
        self.assertIn("catch/0.1@user/testing from local cache", t.out)
        self.assertIn("catch/0.1@user/testing:5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9 - Skip",
                      t.out)
        self.assertIn("catch/0.1@user/testing:5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9 - Cache",
                      t.out)
        conanbuildinfo = load(os.path.join(t.current_folder, "conanbuildinfo.txt"))
        self.assertIn('MYENV=["myenvcatch0.1env"]', conanbuildinfo)
        self.assertIn('[libs_catch]', conanbuildinfo)
        self.assertIn("mylibcatch0.1lib", conanbuildinfo)

    def test_build_requires_diamond(self):
        t = TestClient()
        t.save({"conanfile.py": str(TestConanFile("libA", "0.1"))})
        t.run("create . libA/0.1@user/testing")

        t.save({"conanfile.py": str(TestConanFile("libB", "0.1",
                                                  requires=["libA/0.1@user/testing"]))})
        t.run("create . libB/0.1@user/testing")

        t.save({"conanfile.py": str(TestConanFile("libC", "0.1",
                                                  build_requires=["libB/0.1@user/testing",
                                                                  "libA/0.1@user/testing"]))})
        t.run("create . libC/0.1@user/testing")
        self.assertIn("libC/0.1@user/testing: Created package", t.out)

    def create_with_tests_and_build_requires_test(self):
        client = TestClient()
        # Generate and export the build_require recipe
        conanfile = """from conans import ConanFile
class MyBuildRequire(ConanFile):
    def package_info(self):
        self.env_info.MYVAR="1"
"""
        client.save({"conanfile.py": conanfile})
        client.run("create . Build1/0.1@conan/stable")
        client.save({"conanfile.py": conanfile.replace('MYVAR="1"', 'MYVAR2="2"')})
        client.run("create . Build2/0.1@conan/stable")

        # Create a recipe that will use a profile requiring the build_require
        client.save({"conanfile.py": """from conans import ConanFile
import os

class MyLib(ConanFile):
    build_requires = "Build2/0.1@conan/stable"
    def build(self):
        assert(os.environ['MYVAR']=='1')
        assert(os.environ['MYVAR2']=='2')

""", "myprofile": '''
[build_requires]
Build1/0.1@conan/stable
''',
                    "test_package/conanfile.py": """from conans import ConanFile
import os

class MyTest(ConanFile):
    def build(self):
        assert(os.environ['MYVAR']=='1')
    def test(self):
        self.output.info("TESTING!!!")
"""}, clean_first=True)

        # Test that the build require is applyed to testing
        client.run("create . Lib/0.1@conan/stable --profile=./myprofile")
        self.assertEqual(1, str(client.out).count("Lib/0.1@conan/stable: "
                                                  "Applying build-requirement:"
                                                  " Build1/0.1@conan/stable"))
        self.assertIn("TESTING!!", client.out)

    def test_dependents_txt(self):
        client = TestClient()
        boost = """from conans import ConanFile
class Boost(ConanFile):
    def package_info(self):
        self.env_info.PATH.append("myboostpath")
"""
        client.save({CONANFILE: boost})
        client.run("create . Boost/1.0@user/channel")
        other = """[build_requires]
Boost/1.0@user/channel
"""
        client.save({"conanfile.txt": other}, clean_first=True)
        client.run("install .")

        self.assertIn("""Build requirements
    Boost/1.0@user/channel""", client.out)
        conanbuildinfo = load(os.path.join(client.current_folder, "conanbuildinfo.txt"))
        self.assertIn('PATH=["myboostpath"]', conanbuildinfo)

    def test_dependents(self):
        client = TestClient()
        boost = """from conans import ConanFile
class Boost(ConanFile):
    def package_info(self):
        self.env_info.PATH.append("myboostpath")
"""
        client.save({CONANFILE: boost})
        client.run("create . Boost/1.0@user/channel")
        other = """from conans import ConanFile
import os
class Other(ConanFile):
    requires = "Boost/1.0@user/channel"
    def build(self):
        self.output.info("OTHER PATH FOR BUILD %s" % os.getenv("PATH"))
    def package_info(self):
        self.env_info.PATH.append("myotherpath")
"""
        client.save({CONANFILE: other})
        client.run("create . Other/1.0@user/channel")
        lib = """from conans import ConanFile
import os
class Lib(ConanFile):
    build_requires = "Boost/1.0@user/channel", "Other/1.0@user/channel"
    def build(self):
        self.output.info("LIB PATH FOR BUILD %s" % os.getenv("PATH"))
"""
        client.save({CONANFILE: lib})
        client.run("create . Lib/1.0@user/channel")
        self.assertIn("LIB PATH FOR BUILD myotherpath%smyboostpath" % os.pathsep,
                      client.out)

    def test_applyname(self):
        # https://github.com/conan-io/conan/issues/4135
        client = TestClient()
        mingw = """from conans import ConanFile
class Tool(ConanFile):
    def package_info(self):
        self.env_info.PATH.append("mymingwpath")
"""
        myprofile = """
[build_requires]
consumer*: mingw/0.1@myuser/stable
"""
        app = """from conans import ConanFile
import os
class App(ConanFile):
    name = "consumer"
    def build(self):
        self.output.info("APP PATH FOR BUILD %s" % os.getenv("PATH"))
"""
        client.save({CONANFILE: mingw})
        client.run("create . mingw/0.1@myuser/stable")
        client.save({CONANFILE: app,
                     "myprofile": myprofile})
        client.run("install . -pr=myprofile")
        self.assertIn("conanfile.py (consumer/None): Applying build-requirement: "
                      "mingw/0.1@myuser/stable", client.out)
        client.run("build .")
        self.assertIn("conanfile.py (consumer/None): APP PATH FOR BUILD mymingwpath",
                      client.out)

    def test_transitive(self):
        client = TestClient()
        mingw = """from conans import ConanFile
class Tool(ConanFile):
    def package_info(self):
        self.env_info.PATH.append("mymingwpath")
"""
        myprofile = """
[build_requires]
mingw/0.1@lasote/stable
"""
        gtest = """from conans import ConanFile
import os
class Gtest(ConanFile):
    def build(self):
        self.output.info("GTEST PATH FOR BUILD %s" % os.getenv("PATH"))
"""
        app = """from conans import ConanFile
import os
class App(ConanFile):
    build_requires = "gtest/0.1@lasote/stable"
    def build(self):
        self.output.info("APP PATH FOR BUILD %s" % os.getenv("PATH"))
"""
        client.save({CONANFILE: mingw})
        client.run("create . mingw/0.1@lasote/stable")
        client.save({CONANFILE: gtest})
        client.run("export . gtest/0.1@lasote/stable")
        client.save({CONANFILE: app,
                     "myprofile": myprofile})
        client.run("create . app/0.1@lasote/stable --build=missing -pr=myprofile")
        self.assertIn("app/0.1@lasote/stable: APP PATH FOR BUILD mymingwpath",
                      client.out)
        self.assertIn("gtest/0.1@lasote/stable: GTEST PATH FOR BUILD mymingwpath",
                      client.out)

    def test_profile_order(self):
        client = TestClient()
        mingw = """from conans import ConanFile
class Tool(ConanFile):
    def package_info(self):
        self.env_info.PATH.append("mymingwpath")
"""
        msys = """from conans import ConanFile
class Tool(ConanFile):
    def package_info(self):
        self.env_info.PATH.append("mymsyspath")
"""
        myprofile1 = """
[build_requires]
mingw/0.1@lasote/stable
msys/0.1@lasote/stable
"""
        myprofile2 = """
[build_requires]
msys/0.1@lasote/stable
mingw/0.1@lasote/stable
"""

        app = """from conans import ConanFile
import os
class App(ConanFile):
    def build(self):
        self.output.info("APP PATH FOR BUILD %s" % os.getenv("PATH"))
"""
        client.save({CONANFILE: mingw})
        client.run("create . mingw/0.1@lasote/stable")
        client.save({CONANFILE: msys})
        client.run("create . msys/0.1@lasote/stable")
        client.save({CONANFILE: app,
                     "myprofile1": myprofile1,
                     "myprofile2": myprofile2})
        client.run("create . app/0.1@lasote/stable -pr=myprofile1")
        self.assertIn("app/0.1@lasote/stable: APP PATH FOR BUILD mymingwpath%smymsyspath"
                      % os.pathsep, client.out)
        client.run("create . app/0.1@lasote/stable -pr=myprofile2")
        self.assertIn("app/0.1@lasote/stable: APP PATH FOR BUILD mymsyspath%smymingwpath"
                      % os.pathsep, client.out)

    def test_require_itself(self):
        client = TestClient()
        mytool_conanfile = """from conans import ConanFile
class Tool(ConanFile):
    def build(self):
        self.output.info("BUILDING MYTOOL")
"""
        myprofile = """
[build_requires]
Tool/0.1@lasote/stable
"""
        client.save({CONANFILE: mytool_conanfile,
                     "profile.txt": myprofile})
        client.run("create . Tool/0.1@lasote/stable -pr=profile.txt")
        self.assertEqual(1, str(client.out).count("BUILDING MYTOOL"))

    @parameterized.expand([(requires, ), (requires_range, ), (requirements, ), (override, )])
    def test_build_requires(self, conanfile):
        client = TestClient()
        client.save({CONANFILE: tool_conanfile})
        client.run("export . lasote/stable")

        client.save({CONANFILE: conanfile}, clean_first=True)
        client.run("export . lasote/stable")

        client.run("install MyLib/0.1@lasote/stable --build missing")
        self.assertIn("Tool/0.1@lasote/stable: Generating the package", client.out)
        self.assertIn("ToolPath: MyToolPath", client.out)

        client.run("install MyLib/0.1@lasote/stable")
        self.assertNotIn("Tool", client.out)
        self.assertIn("MyLib/0.1@lasote/stable: Already installed!", client.out)

    @parameterized.expand([(requires, ), (requires_range, ), (requirements, ), (override, )])
    def test_profile_override(self, conanfile):
        client = TestClient()
        client.save({CONANFILE: tool_conanfile2}, clean_first=True)
        client.run("export . lasote/stable")

        client.save({CONANFILE: conanfile,
                     "profile.txt": profile,
                     "profile2.txt": profile.replace("0.3", "[>0.2]")}, clean_first=True)
        client.run("export . lasote/stable")

        client.run("install MyLib/0.1@lasote/stable --profile ./profile.txt --build missing")
        self.assertNotIn("Tool/0.1", client.out)
        self.assertNotIn("Tool/0.2", client.out)
        self.assertIn("Tool/0.3@lasote/stable: Generating the package", client.out)
        self.assertIn("ToolPath: MyToolPath", client.out)

        client.run("install MyLib/0.1@lasote/stable")
        self.assertNotIn("Tool", client.out)
        self.assertIn("MyLib/0.1@lasote/stable: Already installed!", client.out)

        client.run("install MyLib/0.1@lasote/stable --profile ./profile2.txt --build")
        self.assertNotIn("Tool/0.1", client.out)
        self.assertNotIn("Tool/0.2", client.out)
        self.assertIn("Tool/0.3@lasote/stable: Generating the package", client.out)
        self.assertIn("ToolPath: MyToolPath", client.out)

    def options_test(self):
        conanfile = """from conans import ConanFile
class package(ConanFile):
    name            = "first"
    version         = "0.0.0"
    options         = {"coverage": [True, False]}
    default_options = "coverage=False"
    def build(self):
        self.output.info("Coverage: %s" % self.options.coverage)
    """
        client = TestClient()
        client.save({"conanfile.py": conanfile})
        client.run("export . lasote/stable")

        consumer = """from conans import ConanFile

class package(ConanFile):
    name            = "second"
    version         = "0.0.0"
    default_options = "first:coverage=True"
    build_requires  = "first/0.0.0@lasote/stable"
"""
        client.save({"conanfile.py": consumer})
        client.run("install . --build=missing -o Pkg:someoption=3")
        self.assertIn("first/0.0.0@lasote/stable: Coverage: True", client.out)

    def failed_assert_test(self):
        # https://github.com/conan-io/conan/issues/5685
        client = TestClient()
        client.save({"conanfile.py": GenConanfile()})
        client.run("export . common/1.0@test/test")

        req = textwrap.dedent("""
            from conans import ConanFile
            class BuildReqConan(ConanFile):
                requires = "common/1.0@test/test"
            """)
        client.save({"conanfile.py": req})
        client.run("export . req/1.0@test/test")
        client.run("export . build_req/1.0@test/test")

        build_req_req = textwrap.dedent("""
            from conans import ConanFile
            class BuildReqConan(ConanFile):
                requires = "common/1.0@test/test"
                build_requires = "build_req/1.0@test/test"
        """)
        client.save({"conanfile.py": build_req_req})
        client.run("export . build_req_req/1.0@test/test")

        consumer = textwrap.dedent("""
                    [requires]
                    req/1.0@test/test
                    [build_requires]
                    build_req_req/1.0@test/test
                """)
        client.save({"conanfile.txt": consumer}, clean_first=True)
        client.run("install . --build=missing")
        # This used to assert and trace, now it works
        self.assertIn("conanfile.txt: Applying build-requirement: build_req_req/1.0@test/test",
                      client.out)

