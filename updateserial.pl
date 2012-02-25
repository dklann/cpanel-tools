#!/usr/bin/perl
# Update Serial Version 3
#
# Network Data Center Host, Inc 
# support@ndchost.com
#

use strict;
use Getopt::Std;

eval { require DNS::ZoneParse; };
if ($@) {
	if ( -f "/scripts/perlinstaller" ) {
		print "You are missing the DNS::ZoneParse perl module.  We will attempt to install it now...";
		system("/scripts/perlinstaller DNS::ZoneParse >/dev/null 2>&1");
		print "Done\n";
		eval { require DNS::ZoneParse; };
		if ($@) {
			print "Module Install Failed, Please install this module manually and re-run this script\n";
			exit 1;
		} else {
			print "Module Successfully Installed and Loaded!\n";
		}
	} else {
		print "This script requires the DNS::ZoneParse perl module to be installed.  Please install this perl module and re-run this script\n";
		exit 1;
	}
}

my %opts;
getopts('d:', \%opts);

unless ($opts{'d'} && -d $opts{'d'}) {
	print "Usage: $0 -d <path to named zone files>\n\n";
	print "Example: $0 -d /var/named\n\n";
	exit 1;
}

my $zone_path	= $opts{'d'};

my ($login,$pass,$uid,$gid) = getpwnam('named')
   or die "Failed to get uid/gid for user: named";

print "Zone Serial Incrementer\t\t\t\tNDCHost.com\n\n";
print "!WARNING | make sure to make a backup of your $zone_path dir | WARNING!\n";
print "!WARNING | press ctrl+c now to abort, you have 5 seconds | WARNING!\n\n";
sleep 5;

if (-e "/etc/rc.d/init.d/named") {
	system("/etc/rc.d/init.d/named stop");
} else {
	print "You Should stop named if you have not done so\n";
	sleep 5;
}

print "Building array of Zones...";
opendir(ZONES,"$zone_path");
my @ZONES = readdir(ZONES);
closedir(ZONES);
print "Complete\n\n";

foreach(@ZONES) {
	next unless /\.db$/;
	updateserial($_);
}
if( -e "/etc/rc.d/init.d/named") {
	system("/etc/rc.d/init.d/named start");
} else { 
	print "You can now start/restart named\n";
	sleep 5;
}


sub updateserial() {
	my($zonedb) = @_;

	my $zonefile = DNS::ZoneParse->new("$zone_path/$zonedb");
	my $soa         = $zonefile->soa();
	my $prevSerial = $soa->{serial};
	my $newSerial = $zonefile->new_serial();
	print "Modifying $zonedb -> old serial(".$prevSerial.") - newserial(".$newSerial.")\n";
	rename $zone_path."/".$zonedb, $zone_path."/".$zonedb."-serial-".$prevSerial;
	open NEWZONE, ">".$zone_path."/".$zonedb;
	print NEWZONE $zonefile->output();
	close NEWZONE;
	chown $uid, $gid, $zone_path."/".$zonedb;
}
