#!/usr/bin/env python2

import os
import sys
import subprocess
import time
from optparse import OptionParser

def vagrant(params, cwd=None, printout=False):
    """Run vagrant.

    :param: list of parameters to pass to vagrant
    :cwd: directory to run in, or None for current directory
    :printout: True to print output in realtime, False to just
               return it
    :returns: (ret, out) where ret is the return code, and out
               is the stdout (and stderr) from vagrant
    """
    p = subprocess.Popen(['vagrant'] + params, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = ''
    if printout:
        while True:
            line = p.stdout.readline()
            if len(line) == 0:
                break
            print line,
            out += line
        p.wait()
    else:
        out = p.communicate()[0]
    return (p.returncode, out)

boxfile = 'buildserver.box'
serverdir = 'buildserver'

parser = OptionParser()
parser.add_option("-v", "--verbose", action="store_true", default=False,
                      help="Spew out even more information than normal")
parser.add_option("-c", "--clean", action="store_true", default=False,
                      help="Build from scratch, rather than attempting to update the existing server")
options, args = parser.parse_args()

config = {}
execfile('makebs.config.py', config)

if not os.path.exists('makebuildserver.py') or not os.path.exists(serverdir):
    print 'This must be run from the correct directory!'
    sys.exit(1)

if os.path.exists(boxfile):
    os.remove(boxfile)

if options.clean:
    vagrant(['destroy', '-f'], cwd=serverdir, printout=options.verbose)

# Update cached files.
cachedir = os.path.join('buildserver', 'cache')
if not os.path.exists(cachedir):
    os.mkdir(cachedir)
cachefiles = [
    ('android-sdk_r22.3-linux.tgz',
     'http://dl.google.com/android/android-sdk_r22.3-linux.tgz',
     '4077575c98075480e0156c10e48a1521e31c7952768271a206870e6813057f4f'),
    ('gradle-1.9-bin.zip',
     'http://services.gradle.org/distributions/gradle-1.9-bin.zip',
     '097ddc2bcbc9da2bb08cbf6bf8079585e35ad088bafd42e8716bc96405db98e9'),
    ('Kivy-1.7.2.tar.gz',
     'http://pypi.python.org/packages/source/K/Kivy/Kivy-1.7.2.tar.gz',
     '0485e2ef97b5086df886eb01f8303cb542183d2d71a159466f99ad6c8a1d03f1')
    ]
if config['arch64']:
    cachefiles.extend([
    ('android-ndk-r9b-linux-x86_64.tar.bz2',
     'http://dl.google.com/android/ndk/android-ndk-r9b-linux-x86_64.tar.bz2',
     '8956e9efeea95f49425ded8bb697013b66e162b064b0f66b5c75628f76e0f532'),
    ('android-ndk-r9b-linux-x86_64-legacy-toolchains.tar.bz2',
     'http://dl.google.com/android/ndk/android-ndk-r9b-linux-x86_64-legacy-toolchains.tar.bz2',
     'de93a394f7c8f3436db44568648f87738a8d09801a52f459dcad3fc047e045a1')])
else:
    cachefiles.extend([
    ('android-ndk-r9b-linux-x86.tar.bz2',
     'http://dl.google.com/android/ndk/android-ndk-r9b-linux-x86.tar.bz2',
     '748104b829dd12afb2fdb3044634963abb24cdb0aad3b26030abe2e9e65bfc81'),
    ('android-ndk-r9b-linux-x86-legacy-toolchains.tar.bz2',
     'http://dl.google.com/android/ndk/android-ndk-r9b-linux-x86-legacy-toolchains.tar.bz2',
     '606aadf815ae28cc7b0154996247c70d609f111b14e44bcbcd6cad4c87fefb6f')])
wanted = []
for f, src, shasum in cachefiles:
    if not os.path.exists(os.path.join(cachedir, f)):
        print "Downloading " + f + " to cache"
        if subprocess.call(['wget', src], cwd=cachedir) != 0:
            print "...download of " + f + " failed."
            sys.exit(1)
    if shasum:
        p = subprocess.Popen(['shasum', '-a', '256', os.path.join(cachedir, f)],
                stdout=subprocess.PIPE)
        v = p.communicate()[0].split(' ')[0]
        if v != shasum:
            print "Invalid shasum of '" + v + "' detected for " + f
            sys.exit(1)
        else:
            print "...shasum verified for " + f

    wanted.append(f)


# Generate an appropriate Vagrantfile for the buildserver, based on our
# settings...
vagrantfile = """
Vagrant::Config.run do |config|

  config.vm.box = "{0}"
  config.vm.box_url = "{1}"

  config.vm.customize ["modifyvm", :id, "--memory", "{2}"]

  config.vm.provision :shell, :path => "fixpaths.sh"
""".format(config['basebox'], config['baseboxurl'], config['memory'])
if 'aptproxy' in config and config['aptproxy']:
    vagrantfile += """
  config.vm.provision :shell, :inline => 'sudo echo "Acquire::http {{ Proxy \\"{0}\\"; }};" > /etc/apt/apt.conf.d/02proxy && sudo apt-get update'
""".format(config['aptproxy'])
vagrantfile += """
  config.vm.provision :chef_solo do |chef|
    chef.cookbooks_path = "cookbooks"
    chef.log_level = :debug 
    chef.json = {
      :settings => {
        :sdk_loc => "/home/vagrant/android-sdk",
        :ndk_loc => "/home/vagrant/android-ndk",
        :user => "vagrant"
      }
    }
    chef.add_recipe "fdroidbuild-general"
    chef.add_recipe "android-sdk"
    chef.add_recipe "android-ndk"
    chef.add_recipe "kivy"
  end
end
"""

# Check against the existing Vagrantfile, and if they differ, we need to
# create a new box:
vf = os.path.join(serverdir, 'Vagrantfile')
writevf = True
if os.path.exists(vf):
    vagrant(['halt'], serverdir)
    with open(vf, 'r') as f:
        oldvf = f.read()
    if oldvf != vagrantfile:
        print "Server configuration has changed, rebuild from scratch is required"
        vagrant(['destroy', '-f'], serverdir)
    else:
        print "Re-provisioning existing server"
        writevf = False
else:
    print "No existing server - building from scratch"
if writevf:
    with open(vf, 'w') as f:
        f.write(vagrantfile)


print "Configuring build server VM"
returncode, out = vagrant(['up'], serverdir, printout=True)
with open(os.path.join(serverdir, 'up.log'), 'w') as log:
    log.write(out)
if returncode != 0:
    print "Failed to configure server"
    sys.exit(1)

print "Writing buildserver ID"
p = subprocess.Popen(['git', 'rev-parse', 'HEAD'], stdout=subprocess.PIPE)
buildserverid = p.communicate()[0].strip()
print "...ID is " + buildserverid
subprocess.call(
    ['vagrant', 'ssh', '-c', 'sh -c "echo {0} >/home/vagrant/buildserverid"'
    .format(buildserverid)],
    cwd=serverdir)

print "Stopping build server VM"
vagrant(['halt'], serverdir)

print "Waiting for build server VM to be finished"
ready = False
while not ready:
    time.sleep(2)
    returncode, out = vagrant(['status'], serverdir)
    if returncode != 0:
        print "Error while checking status"
        sys.exit(1)
    for line in out.splitlines():
        if line.startswith("default"):
            if line.find("poweroff") != -1:
                ready = True
            else:
                print "Status: " + line

print "Packaging"
vagrant(['package', '--output', os.path.join('..', boxfile)], serverdir)
print "Adding box"
vagrant(['box', 'add', 'buildserver', boxfile, '-f'])

os.remove(boxfile)

