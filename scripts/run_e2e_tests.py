import argparse
import atexit
import fileinput
import os
import platform
import re
import subprocess
import sys
import time

import python_utils

from scripts import build
from scripts import common
from scripts import install_third_party_libs
from scripts import setup
from scripts import setup_gae

CHROME_DRIVER_VERSION = '2.41'

WEB_DRIVER_PORT = 4444
GOOGLE_APP_ENGINE_PORT = 9001
PROTRACTOR_BIN_PATH = os.path.join(common.NODE_MODULES_PATH, 'protractor', 'bin', 'protractor')

_PARSER = argparse.ArgumentParser(description="""
Run this script from the oppia root folder:
   bash scripts/run_e2e_tests.sh

The root folder MUST be named 'oppia'.


  --suite=suite_name Performs test for different suites, here suites are the
        name of the test files present in core/tests/protractor_desktop/ and
        core/test/protractor/ dirs. e.g. for the file
        core/tests/protractor/accessibility.js use --suite=accessibility.
        For performing a full test, no argument is required.
Note: You can replace 'it' with 'fit' or 'describe' with 'fdescribe' to run a
single test or test suite.
""")

_PARSER.add_argument(
    '--browserstack',
    help='Run the tests on browserstack using the'
         'protractor-browserstack.conf.js file.',
    action='store_true')
_PARSER.add_argument(
    '--skip-install',
    help='If true, skips installing dependencies. The default value is false.',
    action='store_true')
_PARSER.add_argument(
    '--sharding', default=True, type=bool,
    help='Disables/Enables parallelization of protractor tests.'
         'Sharding must be disabled (either by passing in false to --sharding'
         ' or 1 to --sharding-instances) if running any tests in isolation'
         ' (fit or fdescribe).',
    )
_PARSER.add_argument(
    '--sharding-instances', type=str, default='3',
    help='Sets the number of parallel browsers to open while sharding.'
         'Sharding must be disabled (either by passing in false to --sharding'
         ' or 1 to --sharding-instances) if running any tests in isolation'
         ' (fit or fdescribe).')
_PARSER.add_argument(
    '--prod_env',
    help='Run the tests in prod mode. Static resources are served from'
         ' build directory and use cache slugs.',
    action='store_true')

_PARSER.add_argument(
    '--suite', default='full',
    help='Performs test for different suites, here suites are the'
         'name of the test files present in core/tests/protractor_desktop/ and'
         'core/test/protractor/ dirs. e.g. for the file'
         'core/tests/protractor/accessibility.js use --suite=accessibility.'
         'For performing a full test, no argument is required.')

SUBPROCESSES = []

def check_screenshot():
    if not os.path.isdir(os.path.join('..', 'protractor-screenshots')):
        return
    python_utils.PRINT("""
Note: If ADD_SCREENSHOT_REPORTER is set to true in
core/tests/protractor.conf.js, you can view screenshots
of the failed tests in ../protractor-screenshots/"
""")

def cleanup():
    processes_to_kill = [
        re.compile(r'.*[Dd]ev_appserver\.py --host 0\.0\.0\.0 --port 9001.*'),
        re.compile(
            r'node_modules(/|\\)webdriver-manager(/|\\)selenium'),
        re.compile('.*chromedriver_%s.*' % CHROME_DRIVER_VERSION)
    ]
    for p in SUBPROCESSES:
        p.kill()

    for p in processes_to_kill:
        common.kill_processes_based_on_regex(p)

def check_running_instance(*ports):
    for port in ports:
        if common.is_port_open(port):
            python_utils.PRINT("""
There is already a server running on localhost:%s.
Please terminate it before running the end-to-end tests.
    Exiting.
            """ % port)
            sys.exit(1)

def wait_for_port(port):
    while not common.is_port_open(port):
        time.sleep(1)

def tweak_constant_ts(constant_file, dev_mode):
    regex = re.compile('"DEV_MODE": .*')
    constants_env_variable = '"DEV_MODE": %s' % (
        'true' if dev_mode else 'false')
    for line in fileinput.input(
           files=[constant_file], inplace=True, backup='.bak'):
        line = line.replace("\n", "")
        line = regex.sub(constants_env_variable, line)
        python_utils.PRINT('%s' % line)

def run_webdriver_manager(commands, wait=True):
    webdriver_bin = os.path.join(
        common.CURR_DIR, 'node_modules', '.bin', 'webdriver-manager')
    web_driver_command = ['node', webdriver_bin]
    web_driver_command.extend(commands)
    p = subprocess.Popen(web_driver_command, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    if wait:
        stdout, err = p.communicate()
        python_utils.PRINT(stdout)
        python_utils.PRINT(err)
    else:
        SUBPROCESSES.append(p)


def setup_and_install_dependencies():
    install_third_party_libs.main(args=[])
    setup.main(args=[])
    setup_gae.main(args=[])

def build_js_files(dev_mode, run_on_browserstack):
    constant_file = os.path.join(common.CURR_DIR, 'assets', 'constants.ts')
    tweak_constant_ts(constant_file, dev_mode)
    if not dev_mode:
        python_utils.PRINT('  Generating files for production mode...')
    else:
        webpack_bin = os.path.join(
            common.CURR_DIR, 'node_modules', 'webpack', 'bin', 'webpack.js')
        common.run_cmd(
            ['node', webpack_bin, '--config', 'webpack.dev.config.ts'])
    if run_on_browserstack:
        python_utils.PRINT(' Running the tests on browsertack...')
    build.main(args=['--prod_env'] if not dev_mode else [])
    os.remove('%s.bak' % constant_file)

def start_webdriver_manager():
    os_name = platform.system()
    run_webdriver_manager(['update', '--versions.chrome', CHROME_DRIVER_VERSION])
    run_webdriver_manager(
        ['start', '--versions.chrome', CHROME_DRIVER_VERSION,
        '--detach', '--quiet'])
    run_webdriver_manager(
        ['start', '2>%snull' % '$' if os_name == 'Windows' else ''], False)

def run_e2e_tests(run_on_browserstack, sharding, sharding_instances, suite, dev_mode):
    if not run_on_browserstack:
        config_file = os.path.join('core', 'tests', 'protractor.conf.js')
    else:
        config_file = os.path.join('core', 'tests', 'protractor-browserstack.conf.js')
    if not sharding or sharding_instances == "1":
        p = subprocess.Popen(['node', PROTRACTOR_BIN_PATH, config_file, '--suite', suite, '--params.devMode=%s' % dev_mode])
    else:
        p = subprocess.Popen(['node', PROTRACTOR_BIN_PATH, config_file, '--capabilities.shardTestFiles=%s' % sharding,  '--capabilities.maxInstances=%s' % sharding_instances, '--suite', suite,  '--params.devMode="%s"' % dev_mode])
    p.communicate()

def main(args=None):
    sys.path.insert(1, os.path.join(common.THIRD_PARTY_DIR, 'psutil-5.6.7'))
    parsed_args = _PARSER.parse_args(args=args)
    atexit.register(cleanup)
    check_running_instance(8181, 9001)
    setup_and_install_dependencies()
    dev_mode = not parsed_args.prod_env
    run_on_browserstack = parsed_args.browserstack
    build_js_files(dev_mode, run_on_browserstack)
    start_webdriver_manager()

    app_yaml_filepath = 'app%s.yaml' % '_dev' if dev_mode else ''

    import dev_appserver
    subprocess.Popen(
        'python %s/dev_appserver.py  --host 0.0.0.0 --port %s '
        '--clear_datastore=yes --dev_appserver_log_level=critical '
        '--log_level=critical --skip_sdk_update_check=true %s' % (
            common.GOOGLE_APP_ENGINE_HOME, GOOGLE_APP_ENGINE_PORT,
            app_yaml_filepath), shell=True)
    wait_for_port(WEB_DRIVER_PORT)
    wait_for_port(GOOGLE_APP_ENGINE_PORT)
    if os.path.isdir(os.path.join(os.pardir, 'protractor-screenshots')):
        os.rmdir(os.path.join(os.pardir, 'protractor-screenshots'))
    run_e2e_tests(run_on_browserstack, parsed_args.sharding, parsed_args.sharding_instances, parsed_args.suite, dev_mode)

if __name__ == '__main__':
    main()
