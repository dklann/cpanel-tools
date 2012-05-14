#!/usr/bin/perl
#WHMADDON:bulk-dns-add:Bulk DNS Generate (zonemaker)
#ACLS:create-dns

#      _|_|    _|                        _|                                                    
#    _|    _|      _|  _|_|    _|_|_|  _|_|_|_|  _|  _|_|    _|_|      _|_|_|  _|_|_|  _|_|
#    _|_|_|_|  _|  _|_|      _|_|        _|      _|_|      _|_|_|_|  _|    _|  _|    _|    _|
#    _|    _|  _|  _|            _|_|    _|      _|        _|        _|    _|  _|    _|    _|
#    _|    _|  _|  _|        _|_|_|        _|_|  _|          _|_|_|    _|_|_|  _|    _|    _|

############################################################################################
#
# This script enables bulk addition of BIND zone records. See the perldoc for more details.
#
############################################################################################

# BEGIN is executed before anything else in the script
# this sets up the search path for library modules
BEGIN {
    unshift @INC,
    '/usr/local/cpanel',
    '/usr/local/cpanel/whostmgr/docroot/cgi',
    '/usr/local/cpanel/cpaddons',
    '/home/dklann/perl5/lib/perl5';
}

use strict;
use warnings qw( all );

use Data::Dumper;
use CGI qw( :all );
use CGI::Carp qw( fatalsToBrowser );
use LWP::UserAgent;
use JSON::PP;
use Cpanel;
use Cpanel::PipeHandler     ();
use Cpanel::HttpRequest     ();
use Cpanel::StringFunc      ();
use Cpanel::Config          ();
use Whostmgr::HTMLInterface ();
use Whostmgr::ACLS ();
use Text::Wrap;
use Text::Diff::FormattedHTML;
use File::stat;
use Net::IP qw(:PROC);

use constant DEBUG  => 1;

use constant BASE_URL => 'http://localhost:2086/json-api';
use constant NAMEDIR => '/var/named';
use constant DEFAULT_COMMENT => 'Comments for this block of addresses. This will be placed above the block of addresses.';
use constant SUFFIX => '.NEW';

sub main();
sub getFormData( $ );
sub getConfirmation( $ );
sub processFormData( $ );
sub commitChanges( $ );
sub authorizedRequest( $$$@ );
sub processJSONresponse( $$$ );
sub apiMessageDisplay ( $$$ );
sub newZoneFile ( $$$ );
sub addOrReplace( $$$$ );
sub networkAddr( $ );
sub incrementSerial ( $$ );
sub pushChanges( $@ );

# run it
main;

1;

# main process
sub main() {

    my $w = CGI->new();
    my @javaScript = <DATA>;

    Whostmgr::ACLS::init_acls();

    print
	$w->header( -expires => '-1D' ),
	$w->start_html(
	    -title => 'Bulk DNS Generate (zonemaker)',
	    -script => join( "", @javaScript ),
	    -style => { -type => 'text/css', -code => diff_css() },
	);

    Whostmgr::HTMLInterface::defheader( '', '', '/cgi/addon_bulk-dns-add.cgi' );

    print
	$w->p( 'phase: ', $w->param( 'phase' ) || '0' ), "\n" if ( DEBUG );

    # query the form parameters to see which phase we are in and what
    # task to perform during this run
    if ( $w->param( 'phase' ) == 3 ) {
	commitChanges( $w );
    } elsif ( $w->param( 'phase' ) == 2 ) {
	processFormData( $w );
    } elsif ( $w->param( 'phase' ) == 1 ) {
	getConfirmation( $w );
    } else {
	getFormData( $w );
    }

    Whostmgr::HTMLInterface::sendfooter();

    print $w->end_html(), "\n";
}

# phase 0: gather initial zone and domain data
sub getFormData( $ ) {
    my $w = shift;

    # Ensure they have proper access before doing anything else. See
    # http://docs.cpanel.net/twiki/bin/view/SoftwareDevelopmentKit/CreatingWhmPlugins#Access%20Control
    # for details.
    if ( Whostmgr::ACLS::checkacl( 'create-dns' )) {
	my $ua = LWP::UserAgent->new;

	print
	    $w->h1( 'Bulk DNS Generator (formerly known as zonemaker)' ), "\n",
	    $w->p( 'Use this form to generate a set of entries to add to a DNS zone.' );

	##################################################
	###  get initial pop-up menu data from cPanel  ###
	##################################################
	# $domains is the JSON data structure returned from the query
	# @domains is the array containing a sorted list of unique domains
	# @forwardDomains contains "normal" domains, and
	# @inaddrDomains contains "reverse" (in-addr.arpa) domains
	my $domains = authorizedRequest( $w, $ua, 'listzones', ( 'api.version=1', 'searchtype=owner', ));
	my @domains = ();
	my @forwardDomains = ();
	my @inaddrDomains = ();

	if ( $domains ) {

	    # "map/reduce": map() gives an array of domain hashes,
	    # keys() gives an array of owners, sort(grep()) drops the
	    # in-addr.arpa zones, the last sort(grep()) gets a list of
	    # in-addr.arpa zones sorted by address in normal order
	    @domains = map( { $_->{domain} } @{$domains->{data}->{zone}} );
	    @domains = keys( %{{ map( { $_ => 1 } @domains ) }} );
	    @forwardDomains = sort( grep( !/(in-addr|ip6)\.arpa/, @domains ));
	    # this godawful sort does the Right Thing(tm)
	    @inaddrDomains = sort {
		my @a = $a =~ /(\d+)\.(\d+)\.(\d+)\.(in-addr\.arpa|ip6\.arpa)/;
		my @b = $b =~ /(\d+)\.(\d+)\.(\d+)\.(in-addr\.arpa|ip6\.arpa)/;
		$a[2] <=> $b[2]
		    ||
		    $a[1] <=> $b[1]
		    ||
		    $a[0] <=> $b[0]
	    } grep( /(in-addr|ip6)\.arpa/, @domains );

	    # prepend placeholders for adding a new domain
	    unshift( @forwardDomains, ( '' ));
	    unshift( @inaddrDomains, ( '' ));
	} else {
	    @forwardDomains = ( '' );
	    @inaddrDomains = ( '' );
	}

	print
	    $w->start_form(
		-name => 'bulk_add',
		-method => 'POST',
		-action => '/cgi/addon_bulk-dns-add.cgi',
	    ), "\n";

	print
	    $w->start_div({ -id => 'outer' }),
	    "\n";

	### forward domains
	print
	    $w->table ({ -border => '0', id => 't1' },
		       $w->Tr({ -align => 'left' },
			      $w->th({ -align => 'right' }, 'Choose a forward domain:&nbsp;' ),
			      $w->td(
				  $w->popup_menu(
				      -id => 'existing_forward_domain',
				      -name => 'existing_forward_domain',
				      -values => \@forwardDomains,
				      -onChange => 'showAddNew(this, "forward_domain_textfield")',
				  ),
			      ),
			      $w->td({ -id => 'info_existing_forward_domain' }, '&nbsp;' ),
		       ),
	    ), "\n";

	# hide this <div> at first (style="display: none")
	# the javascript function showAddNew() makes this visible and invisible
	print
	    $w->div({ -id => 'forward_domain_textfield', -style => 'display: none' },
		    $w->table ({ -border => '0', -id => 't2' },
			       $w->Tr({ -align => 'left' },
				      $w->th({ -align => 'right' }, 'New Domain:&nbsp;' ),
				      $w->td(
					  $w->textfield(
					      -id => 'forward_domain',
					      -name => 'forward_domain',
					      -size => '32',
					      -maxlength => '56',
					      -onChange => 'validateHostName(this, "info_forward_domain", true)'
					  ),
				      ),
				      $w->td({ -id => 'info_forward_domain' }, '&nbsp;' ),
			       ),
		    ), "\n"
	    );

	### in-addr.arpa (reverse) domains
	print
	    $w->checkbox(
		-id => 'do_reverse_domain',
		-name => 'do_reverse_domain',
		-checked => 0,
		-label => 'Add reverse domain records',
		-onClick => 'toggleVisibility(this, "reverse_domain"); toggleVisibility(this, "ipv4network");',
	    );

	# hide this <div> at first (style="display: none")
	# the javascript function showAddNew() makes this visible and invisible
	print
	    $w->div( { -id => 'reverse_domain', -style => 'display: none' },
		    $w->table ({ -border => '0', id => 't3' },
			       $w->Tr({ -align => 'left' },
				      $w->th({ -align => 'right' }, 'Choose a reverse domain (check to include):&nbsp;' ),
				      $w->td(
					  $w->popup_menu(
					      -id => 'existing_reverse_domain',
					      -name => 'existing_reverse_domain',
					      -values => \@inaddrDomains,
					  ),
				      ),
				      $w->td({ -id => 'info_existing_reverse_domain' }, '&nbsp;' ),
			       ),
		    ),
		    "\n",
		    $w->div({ -id => 'reverse_domain_textfield', -style => 'display: none' },
			    $w->table ({ -border => '0', -id => 't4' },
				       $w->Tr({ -align => 'left' },
					      $w->th({ -align => 'right' }, 'New Reverse Domain:&nbsp;' ),
					      $w->td(
						  $w->textfield(
						      -id => 'reverse_domain',
						      -name => 'reverse_domain',
						      -size => '32',
						      -maxlength => '56',
						      -onChange => 'validateReverseZone(this, "info_reverse_domain", true)'
						  ),
					      ),
					      $w->td({ -id => 'info_reverse_domain' }, '&nbsp;' ),
				       ),
			    ), "\n"
		    )
	    );

	# the base (CIDR /24) address
	# this block disappears when the user chooses to include a reverse zone
	print
	    $w->div( { -id => 'ipv4network', -style => 'display: block' },
		     $w->table ( { -border => '0' },
				 $w->Tr({ -align => 'left' },
					$w->th({ -align => 'right' }, 'Base Address (first three octets):&nbsp;' ),
					$w->td(
					    $w->textfield(
						-id => 'ipv4network',
						-name => 'ipv4network',
						-size => 11,
						-maxlength => 11,
						-onChange => 'validateBaseAddress(this, "info_ipv4network", true)',
					    ),
					),
					$w->td({ -id => 'info_ipv4network' }, '&nbsp;' ),
				 ), "\n",
		     ), "\n",
	    );

	# fourth octet starting point
	print
	    $w->start_table ({ -border => '0' } ),
	    $w->Tr({ -align => 'left' },
		   $w->th({ -align => 'right' }, 'Fourth octet start:&nbsp;' ),
		   $w->td(
		       $w->textfield(
			   -id => 'ipv4start',
			   -name => 'ipv4start',
			   -size => 3,
			   -maxlength => 3,
			   -onchange  => 'validateNumericRange(this, "info_ipv4start", 0, 255, true)',
		       ),
		   ),
		   $w->td({ -id => 'info_ipv4start' }, '&nbsp;' ),
	    ), "\n";

	# fourth octet ending point
	print
	    $w->Tr({ -align => 'left' },
		   $w->th({ -align => 'right' }, 'Fourth octet end:&nbsp;' ),
		   $w->td(
		       $w->textfield(
			   -id => 'ipv4end',
			   -name => 'ipv4end',
			   -size => 3,
			   -maxlength => 3,
			   -onchange  => 'validateNumericRange(this, "info_ipv4end", (parseInt(document.forms[0].elements["ipv4start"].value) + 1), 255, true)',
		       ),
		   ),
		   $w->td({ -id => 'info_ipv4end' }, '&nbsp;' ),
	    ), "\n";

	# base hostname
	print
	    $w->Tr({ -align => 'left' },
		   $w->th({ -align => 'right' }, 'Base hostname:&nbsp;' ),
		   $w->td(
		       $w->textfield(
			   -id => 'hostname_base',
			   -name => 'hostname_base',
			   -size => 32,
			   -maxlength => 64,
			   -onchange  => 'validateHostName(this, "info_hostname_base", true)',
		       ),
		   ),
		   $w->td({ -id => 'info_hostname_base' }, '&nbsp;' ),
	    ), "\n";

	# hostname number - this number gets incremented for as many records as they
	# chose in the fourth octet range
	# the maximum limit of 999 is arbitrary, but it really cannot be greater than 255, can it?
	print
	    $w->Tr({ -align => 'left' },
		   $w->th({ -align => 'right' }, 'Starting point for hostname increment:&nbsp;' ),
		   $w->td(
		       $w->textfield(
			   -id => 'hostname_offset',
			   -name => 'hostname_offset',
			   -size => 3,
			   -maxlength => 3,
			   -onchange  => 'validateNumericRange(this, "info_hostname_offset", 0, 999, true)',
		       ),
		   ),
		   $w->td({ -id => 'info_hostname_offset' }, '&nbsp;' ),
	    ), "\n";

	print
	    $w->Tr({ -align => 'left' },
		   $w->th({ -align => 'right' }, 'Comments:&nbsp;', $w->br(), '(comments will be wrapped and set off with ";")' ),
		   $w->td(
		       $w->textarea(
			   -id => 'comment',
			   -name => 'comment',
			   -default => DEFAULT_COMMENT,
			   -rows => 4,
			   -columns => 76,
			   -onFocus => 'if (this.value == this.defaultValue) {this.value = "";}',
			   -onBlur => 'if (this.value == "") {this.value="' . DEFAULT_COMMENT . '";}'
		       ),
		   ),
		   $w->td({ -id => 'info_comment' }, '&nbsp;' ),
	    ), "\n";

	print
	    $w->Tr({ -align => 'left' },
		   $w->td(
		       $w->checkbox(
			   -id => 'verbose',
			   -name => 'verbose',
			   -value => 'ON',
			   -label => 'Verbose processing (AKA "debugging")',
		       ),
		   ),
	    ), "\n";

	print
	    $w->Tr({ -align => 'left' },
		   $w->td(
		       $w->submit(
			   -name => 'submit',
			   -label => 'Show Records'
		       ),
		   ),
		   $w->td(
		       $w->button(
			   -name => 'Reset',
			   -value => 'Reset',
			   -label => 'Reset Form',
			   -onClick => 'this.form.reset()',
		       ),
		   ),
	    ), "\n";

	print
	    $w->hidden(
		-name => 'phase',
		-value => '1',
		-default => '1',
	    ),
	    "\n";

	print
	    $w->end_form(), "\n",
	    $w->end_table(), "\n",
	    $w->end_div({ id => 'outer' });

    } else {

	print
	    $w->br(), $w->br(),
	    $w->div({ -align => 'center' },
		    $w->h1( 'Permission denied' ),
		    "\n"
	    );

    }
}

# phase 1: generate zone file entries and permit user to edit them
sub getConfirmation( $ ) {
    my $w = shift;

    # Ensure they have proper access before doing anything else. See
    # http://docs.cpanel.net/twiki/bin/view/SoftwareDevelopmentKit/CreatingWhmPlugins#Access%20Control
    # for details.
    if ( Whostmgr::ACLS::checkacl( 'create-dns' )) {

	# get all the parameters from the completed form
	my $existing_forward_domain = $w->param( 'existing_forward_domain' );
	my $existing_reverse_domain = $w->param( 'existing_reverse_domain' );
	my $do_reverse_domain = $w->param( 'do_reverse_domain' );
	my $ipv4network = $w->param( 'ipv4network' );
	my $ipv4start = $w->param( 'ipv4start' );
	my $ipv4end = $w->param( 'ipv4end' );
	my $hostname_base = $w->param( 'hostname_base' );
	my $hostname_offset = $w->param( 'hostname_offset' );
	my $comment = $w->param( 'comment' );
	my $verbose = $w->param( 'verbose' );

	my $forward_domain = undef;
	my $reverse_domain = undef;

	my @bind = ();

	my $addrCount = $ipv4start;
	my $hostCount = $hostname_offset;

	my %params = $w->Vars();
	my $formatString = undef;
	my @comment = ();

	my @forward_zones = ();
	my @reverse_zones = ();

	my $ua = LWP::UserAgent->new;

	$forward_domain = $existing_forward_domain;
	if ( $do_reverse_domain ) {
	    $reverse_domain = $existing_reverse_domain;
	    $ipv4network = networkAddr( $reverse_domain );
	}

	# make the list of IP addresses and hostnames
	# save the full IP address, the domain, and the numbered hostname
	# use an array of hashes rather than a big hash so we can preserve the order of entries
	for ( $addrCount = $ipv4start; $addrCount <= $ipv4end; $addrCount++ ) {
	    $bind[$addrCount]->{ipv4address} = sprintf( '%s.%d', $ipv4network, $addrCount );
	    $bind[$addrCount]->{resource} = sprintf( '%s-%d', $hostname_base, $hostCount );
	    if ( $do_reverse_domain ) {
		$bind[$addrCount]->{forwardDomain} = $forward_domain;
	    }
	    $hostCount++;
	}
	if ( DEBUG || $verbose ) {
	    print
		$w->div({ -id => 'debugzonerecords' },
			$w->p( 'DEBUG (phase ', $w->param( 'phase' ), '): @bind is:' ), "\n",
			$w->pre( Dumper( @bind )), "\n",
		);
	}

	# strip any hand-entered comment symbols, the default comment, and save the wrapped comment
	my $default_comment = DEFAULT_COMMENT;
	$comment =~ s/^$default_comment$//;
	@comment = split( ' ', $comment );
	push ( @forward_zones, ( wrap( '; ', '; ', grep( !/^;$/, @comment )), "\n" ));


	$formatString = '%-' . length( $hostname_base . '-xxx.' ) . "s\tIN\t%s\t%s\n";

	# build an array of strings to be searched for in the zone files.
	foreach my $record ( @bind ) {
	    next unless ( $record->{ipv4address} );

	    push( @forward_zones,
		  sprintf( $formatString,
			   $record->{resource},
			   'A',
			   $record->{ipv4address}
		  )
		);
	}

	# do the same for the in-addr.arpa zones.
	if ( $do_reverse_domain ) {
	    push ( @reverse_zones, ( wrap( '; ', '; ', grep( !/^;$/, @comment )), "\n" ));

	    $formatString = "%-3d\tIN\t%s\t%s.$forward_domain.\n";

	    for ( my $r = 0; $r <= $#bind; $r++ ) {
		my $record = $bind[$r];
		next unless ( $record->{ipv4address} );
		push( @reverse_zones,
		      sprintf( $formatString,
			       $r,
			       'PTR',
			       $record->{resource}
		      )
		    );
	    }
	}

	print
	    $w->start_div({ -id => 'zonerecords' , -style => 'display: block'} ), "\n",
	    $w->start_form(
		-name => 'review_changes',
		-method => 'POST',
		-action => '/cgi/addon_bulk-dns-add.cgi',
	    ), "\n";
	print
	    $w->p( 'Forward zone data:' ),
	    $w->textarea(
		{
		    -id => 'forward_zone_records',
		    -name => 'forward_zone_records',
		    -rows => $#forward_zones + 1,
		    -columns => 80,
		    -default => join( '', @forward_zones ),
		},
	    ), "\n";

	if ( $do_reverse_domain ) {
	    print
		$w->p( 'Reverse zone data:' ),
		$w->textarea(
		    {
			-id => 'reverse_zone_records',
			-name => 'reverse_zone_records',
			-rows => $#reverse_zones + 1,
			-columns => 80,
			-default => join( '', @reverse_zones ),
		    },
		), "\n";
	}

	# save the parameters from the previous form for the next phase
	foreach my $p ( sort( keys( %params ))) {
	    next if ( $p =~ /phase|submit/ );
	    print
		$w->hidden(
		    -name => $p,
		    -default => $w->param( $p )
		), "\n";
	}

	print
	    $w->br(),
	    $w->submit(
		-name => 'submit',
		-label => 'Ready'
	    ), "\n";

	$w->param( -name => 'phase', -value => '2' );

	print
	    $w->hidden(
		-name => 'phase',
		-default => '2',
		-override => 1,
	    ),
	    "\n";

	print
	    $w->end_form(),
	    $w->end_div({-id => 'zonerecords' } ),
	    "\n";

	print
	    $w->p(
		'Click your browser\'s Back button if you need to make changes.'
	    ), "\n";
    } else {

    	print
    	    $w->br(), $w->br(),
    	    $w->div({ -align => 'center' },
		    $w->h1( 'Permission denied' ),
		    "\n"
    	    );
    }
}

# phase 2: process the inputs and generate new zone file(s)
sub processFormData( $ ) {
    my $w = shift;

    # Ensure they have proper access before doing anything else. See
    # http://docs.cpanel.net/twiki/bin/view/SoftwareDevelopmentKit/CreatingWhmPlugins#Access%20Control
    # for details.
    if ( DEBUG || Whostmgr::ACLS::checkacl( 'create-dns' )) {

	# get all the parameters from the completed form
	my $existing_forward_domain = $w->param( 'existing_forward_domain' );
	my $existing_reverse_domain = $w->param( 'existing_reverse_domain' );
	my $do_reverse_domain = $w->param( 'do_reverse_domain' );
	my $verbose = $w->param( 'verbose' );
	my $forward_zone_records = $w->param( 'forward_zone_records' );
	my $reverse_zone_records = $w->param( 'reverse_zone_records' );

	my $forward_domain = undef;
	my $reverse_domain = undef;

	my %params = $w->Vars();

	my $response = undef;
	my $ua = LWP::UserAgent->new;

	$forward_domain = $existing_forward_domain;
	if ( $do_reverse_domain ) {
	    $reverse_domain = $existing_reverse_domain;
	}

	if ( DEBUG || $verbose ) {
	    print
		$w->div( { -id => 'debugzonerecords' },
			 $w->p( 'DEBUG (phase ', $w->param( 'phase' ), '): forward zone records for: ', $forward_domain ), "\n",
			 $w->pre( $forward_zone_records ), "\n",
		);
	    if ( $do_reverse_domain ) {
		print
		    $w->div( { -id => 'debugzonerecords' },
			     $w->p( 'DEBUG (phase ', $w->param( 'phase' ), '): reverse zone records for: ', $reverse_domain ), "\n",
			     $w->pre( $reverse_zone_records ), "\n",
		    );
	    }
	}

	# update the forward zone file
	if ( -r NAMEDIR . '/' . $forward_domain . '.db' ) {
	    newZoneFile ( $w, $forward_domain, $forward_zone_records );
	} else {
	    print
		$w->p( 'Cannot read zone file ', $forward_domain, ' (', $!, ')' ), "\n";
	}

	if ( $do_reverse_domain ) {
	    # update the reverse zone file
	    if ( -r NAMEDIR . '/' . $reverse_domain . '.db' ) {
		newZoneFile ( $w, $reverse_domain, $reverse_zone_records );
	    } else {
		print
		    $w->p( 'Cannot read zone file ', $reverse_domain, ' (', $!, ')' ), "\n";
	    }
	}

	print
	    $w->p( 'Click the Commit button if the above changes are correct. Otherwise click Back and make necessary changes.' );

	print
	    start_form(
		-name => 'commit_changes',
		-method => 'POST',
		-action => '/cgi/addon_bulk-dns-add.cgi',
	    ), "\n";

	# save the parameters from the previous form for the next phase
	foreach my $p ( sort( keys( %params ))) {
	    next if ( $p =~ /phase|submit/ );
	    print
		$w->hidden(
		    -name => $p,
		    -default => $w->param( $p )
		), "\n";
	}

	print
	    $w->br(),
	    $w->submit(
		-name => 'submit',
		-label => 'Commit'
	    ), "\n";

	$w->param( -name => 'phase', -value => '3' );

	print
	    $w->hidden(
		-name => 'phase',
		-default => '3',
		-override => 1,
	    ),
	    "\n";

	print
	    end_form(),
	    "\n";

    } else {

    	print
    	    $w->br(), $w->br(),
    	    $w->div({ -align => 'center' },
		    $w->h1( 'Permission denied' ),
		    "\n"
    	    );
    }
}

# phase 3: commit the changes after reviewing the diffs
sub commitChanges( $ ) {
    my $w = shift;

    # Ensure they have proper access before doing anything else. See
    # http://docs.cpanel.net/twiki/bin/view/SoftwareDevelopmentKit/CreatingWhmPlugins#Access%20Control
    # for details.
    if ( DEBUG || Whostmgr::ACLS::checkacl( 'create-dns' )) {

	# get all the parameters from the completed form
	my $existing_forward_domain = $w->param( 'existing_forward_domain' );
	my $existing_reverse_domain = $w->param( 'existing_reverse_domain' );
	my $do_reverse_domain = $w->param( 'do_reverse_domain' );
	my $verbose = $w->param( 'verbose' );

	my $forward_domain = undef;
	my $reverse_domain = undef;

	my $pushChanges = undef;

	$forward_domain = $existing_forward_domain;
	if ( $do_reverse_domain ) {
	    $reverse_domain = $existing_reverse_domain;
	}

	my $forwardZoneFileName = NAMEDIR . '/' . $forward_domain . '.db';
	my $reverseZoneFileName = NAMEDIR . '/' . $reverse_domain . '.db';
	my $newForwardZoneFileName = NAMEDIR . '/' . $forward_domain . SUFFIX;
	my $newReverseZoneFileName = NAMEDIR . '/' . $reverse_domain . SUFFIX;

	if ( -r $newForwardZoneFileName ) {
	    if ( -w $forwardZoneFileName ) {

		if ( DEBUG ) {
		    print
			$w->p( 'DEBUG (phase ', $w->param( 'phase' ), '): Would rename( ',
			       $newForwardZoneFileName, ', ', $forwardZoneFileName, ')' ),
			"\n";
		    $pushChanges = 1;
		} else {
		    die( "Could not rename $newForwardZoneFileName to $forwardZoneFileName ($!). Stopped" )
			unless ( rename( $newForwardZoneFileName, $forwardZoneFileName ));

		    # Will not reach this if there was an error.
		    $pushChanges = 1;
		}
	    } else {
		print
		    $w->p( { -style => 'color:red;' },
			   'Exception! ', $forwardZoneFileName, ' is not writable!'
		    ), "\n";
	    }
	} else {
	    print
		$w->p( { -style => 'color:red;' },
		       'Exception! ', $newForwardZoneFileName, ' is not readable!'
		), "\n";
	}

	# We do not set $pushChanges here because we will have already set it above,
	# and we will die() appropriately if something goes wrong here.
	if ( $do_reverse_domain ) {
	    if ( -r $newReverseZoneFileName ) {
		if ( -w $reverseZoneFileName ) {

		    if ( DEBUG ) {
			print
			    $w->p( 'DEBUG (phase ', $w->param( 'phase' ), '): Would rename( ',
				   $newReverseZoneFileName, ', ', $reverseZoneFileName, ')' ),
			    "\n";
		    } else {
			die( "Could not rename $newReverseZoneFileName to $reverseZoneFileName ($!). Stopped" )
			    unless ( rename( $newReverseZoneFileName, $reverseZoneFileName ));
		    }
		} else {
		    print
			$w->p( { -style => 'color:red;' },
			       'Exception! ', $reverseZoneFileName, ' is not writable!'
			), "\n";
		}
	    } else {
		print
		    $w->p( { -style => 'color:red;' },
			   'Exception! ', $newReverseZoneFileName, ' is not readable!'
		    ), "\n";
	    }
	}

	if ( $pushChanges ) {
	    die( "Error pushing changes to cluster servers ($!). Stopped" )
		unless ( pushChanges( $w, ( $forward_domain, $reverse_domain )));

	    print
		$w->p(
		    'Update of ',
		    $forward_domain,
		    $reverse_domain ? " and $reverse_domain " : ' ',
		    'completed successfully',
		), "\n";
	}
    } else {

    	print
    	    $w->br(), $w->br(),
    	    $w->div({ -align => 'center' },
		    $w->h1( 'Permission denied' ),
		    "\n"
    	    );
    }
}

# return a hash reference to response data from a request
sub authorizedRequest( $$$@ ) {
    my $w = shift;
    my $ua = shift;
    my $action = shift;
    my @args = @_;

    my ( $request, $response ) = ( undef, undef );
    my $URL = undef;
    my $jsonRef = undef;

    my $authHash = 'WHM root:653b9361f915790c31cd8072a53b0d836eb931e920ce32f21d6d3edd48d4347858d4b4fdd756c961a27cbbacdacc8ef20ff6401e8a80aeacddd29f6ee5674daa88d0db5781c623e42d15ed839d78309411b164677f6623ca006667c238b772b927c40e368aea3d814232ac157a0fdee9ec441b62a949ff9a4e3d5cd4d5050df29a916afdc709ae55386755bfaa6296b55988681e2a5c5124ede05807657b17b9478d89f83c392cc0ac226eba6453924e54c8b98cb977102f5c00efa55ae65a5b61fe4d3ce8bafc32455bc1c0864b9fddc3b7b7f9400d0a51afb3525e83f5e91ac37c4bab5cd26dcf643f0a4c23e51a2e26b2408f60a91e8456851b6807e651aea4430a606204758b4712916d2a63e7557e76447f886e1c0f5421e2983eb24701477027eef9d2d58249d70fcb82c47321ab297884e6b1157edb3d369725369868985f8cfa373176b15f5a2b625fd58eb45a0d9f0b21007b0e4077414b97a0aed1801a690a33146eb1236a6c9308e5ec8f037c9ffca61e05744812d2a58a6a9a7b837de8395b3196707aabca4c2c4a1d35045215018cc1b686ef0fcc96a968e9c43c8695c23ccddc01e65c27cdfc0ebb087a163da35c8378d2b3f0a29de0a5fc59eeed9ba8f39c2b8e8f459f3d1ecd0f0c';

    # make a complete URL from the arguments passed in
    $URL = BASE_URL . '/' . $action . '?' . join( '&', @args );

    # print $w->pre( Dumper( $URL )), "\n" if ( DEBUG );

    # see http://docs.cpanel.net/twiki/bin/view/SoftwareDevelopmentKit/ApiAuthentication
    if ( $request = HTTP::Request->new( GET => $URL )) {

	$request->header( Authorization => $authHash );
	$response = $ua->request( $request );
    }

    if ( $response ) {
	# print
	#     $w->p( '$response from $ua->request():' ),
	#     $w->pre( Dumper( $response )), "\n" if ( DEBUG ),;

	$jsonRef = processJSONresponse( $w, $action, $response->{'_content'} );

	# print $w->pre( Dumper( $jsonRef )), "\n" if ( DEBUG );
    } else {
	print
	    $w->p( 'ERROR: missing response from $ua->request()' ),
	    $w->pre( Dumper( $response )), "\n";
    }


    $jsonRef;
}

# parse the JSON response from the API call and
# normalize it to something we can deal with
sub processJSONresponse( $$$ ) {
    my $w = shift;
    my $action = shift;
    my $response = shift;

    my $jsonRef = undef;

    if ( $response ) {
	my $json = JSON::PP->new();

	$jsonRef = $json->decode( $response );

	if ( $jsonRef ) {

	    if ( $jsonRef->{metadata} ) {

		if ( $w->param('verbose') || $jsonRef->{metadata}->{result} != 1 ) {
		    print $w->pre( Dumper( $jsonRef )), "\n";
		}

	    } elsif ( $jsonRef->{result} ) {

		if ( $jsonRef->{result}[0]->{status} ) {
		    $jsonRef->{metadata}->{result} = $jsonRef->{result}[0]->{status};
		    $jsonRef->{metadata}->{reason} = 'API Success';
		    $jsonRef->{metadata}->{statusmsg} = $jsonRef->{result}[0]->{statusmsg};
		} else {
		    $jsonRef->{metadata}->{result} = $jsonRef->{result}[0]->{status};
		    $jsonRef->{metadata}->{reason} = 'API Error';
		    $jsonRef->{metadata}->{statusmsg} = $jsonRef->{result}[0]->{statusmsg};
		}

	    } else {
		print
		    $w->p( 'ERROR: unknown JSON structure in $response:' ), "\n",
		    $w->pre( Dumper( $jsonRef )), "\n";
	    }
	} else {
	    print $w->p( 'ERROR: unable to decode JSON from ', $response ), "\n";
	}
    } else {
	print $w->p( 'ERROR: received NULL response from adddns request' ), "\n";
    }

    $jsonRef;
}

# display a message based on cPanel API JSON data
sub apiMessageDisplay ( $$$ ) {
    my $w = shift;
    my $response = shift;
    my $message = shift;

    print
	$w->h1( $message ), "\n";

    if ( $response ) {
	print
	    $w->p(
		'Result: ', $response->{metadata}->{result},
		$w->br(),
		'Reason: ', $response->{metadata}->{reason},
		$w->br(),
		$w->pre( $response->{metadata}->{statusmsg}, "\n" ),
	    ), "\n";
    }
}

# update a zone file with a named based on the $domainName and new records in $zoneRecords
sub newZoneFile ( $$$ ) {
    my $w = shift;
    my $domainName = shift;
    my $zoneRecords = shift;

    my $zoneFileName = NAMEDIR . '/' . $domainName . '.db';
    my $newZoneFileName = NAMEDIR . '/' . $domainName . SUFFIX;
    my @zoneFileContents = ();
    my @newZoneFileContents = ();

    # the map statement in addOrReplace() is different for reverse zones
    my $reverseZone = ( $domainName =~ /(in-addr|ip6)\.arpa/i );

    # metadata for the existing file will be applied to the new file
    my $sb = stat( $zoneFileName );

    # place the new zone records into an array for further processing
    my @newLines = split( /\n/, $zoneRecords );

    open( ZF, $zoneFileName ) || die "Cannot open $zoneFileName for reading ($!). Stopped";
    @zoneFileContents = <ZF>;
    close( ZF );
    chomp( @zoneFileContents );

    # replace the records if they exist, else add them to the end of the existing records
    @newZoneFileContents = addOrReplace ( $w, \@zoneFileContents, \@newLines, $reverseZone );

    # set the serial number for the zone
    if ( incrementSerial( $w, \@newZoneFileContents )) {

	print
	    $w->h1( $zoneFileName ),
	    $w->p( 'Showing differences between old and new versions of the zone file.' ), "\n";

	# use Text::Diff::FormattedHTML to display the old and the new zone file contents
	# (chop lines at 80 characters just for display purposes)
	print
	    diff_strings(
		join( "\n", map( substr($_, 0, 79), @zoneFileContents )),
		join( "\n", map( substr($_, 0, 79), @newZoneFileContents ))
	    );

	if ( -f $newZoneFileName ) {
	    unlink( $newZoneFileName );
	}

	# save @newZoneFileContents to a file for processing in the next phase
	open( NEW, ">$newZoneFileName" ) || die( "Cannot open $newZoneFileName for writing ($!). Stopped" );
	print NEW join( "\n", @newZoneFileContents ), "\n" || die( "Could not write to $newZoneFileName ($!). Stopped" );
	close( NEW );

	die( "Cannot set ownership of new zone file $newZoneFileName ($!). Stopped" )
	    unless ( chown( $sb->uid, $sb->gid, $newZoneFileName ) == 1 );
	die( "Cannot set permissions for new zone file $newZoneFileName ($!). Stopped" )
	    unless ( chmod( $sb->mode & 07777, $newZoneFileName ) == 1 );

    } else {

	print
	    $w->h1( { -style => 'color:red;' },
		    'Exception: Could not update serial number for zone file ', $zoneFileName, '!',
	    ),
	    "\n";
    }
}

# return an array containing the new contents of the zone file
sub addOrReplace( $$$$ ) {
    my $w = shift;
    my $oldContents = shift;
    my $newLines = shift;
    my $reverseZone = shift;

    my @newContents = @$oldContents;
    my $successExpr = qr/^1$/;

    foreach my $line ( @$newLines ) {

	my @result = ();

	# this line format is established in the subrouting getConfirmation() with variable $formatString
	# and make sure everything is in lower case
	my ( $hostName, $class, $type, $resourceName ) = split( ' ', $line );
	# $hostName = lc( $hostName );
	# $class = lc( $class );
	# $type = lc( $type );
	# $resourceName = lc( $resourceName );

	if ( $reverseZone ) {

	    # reverse zones: replace the resource name (the right-hand field)

	    # back references (items in parentheses):
	    # $1 - first word on the line (the hostname), what we search for
	    # $2 - spaces + TTL (empty if no TTL)
	    # $3 - TTL (empty if no TTL)
	    # $4 - class (IN)
	    # $5 - type (A, PTR, etc)
	    # $6 - fqdn (resource name), what we replace
	    #                      host       TTL          class     type  resource name
	    my $searchExpr = qr/^($hostName)(\s+(\d+))*\s+($class)\s+(ptr)\s+(.*)\s*$/i;

	    @result = map( { s/$searchExpr/$1$2\t$4\t$5\t$resourceName/; } @newContents );

	    # the above map() call returns an array of success or undef
	    # for each element of @newContents depending on the result of
	    # the substitution (s///)
	    if ( ! grep( /$successExpr/, @result )) {

		# add the new line to the end of the zone file contents if no match succeeded
		push( @newContents, $line );
	    }
	} else {

	    # forward zones: replace the hostname (the left-hand field)

	    # back references (items in parentheses):
	    # $1 - first char on the line
	    # $2 - first word on the line (the hostname), what we replace
	    # $3 - spaces + TTL (empty if no TTL)
	    # $4 - TTL (empty if no TTL)
	    # $5 - class (IN)
	    # $6 - type (A, PTR, etc)
	    # $7 - IP address (resource name), what we search for
	    #                      host       TTL          class    type  resource name
	    my $searchExpr = qr/^(([^;\s])+)(\s+(\d+))*\s+($class)\s+(a)\s+($resourceName)\s*$/i;

	    @result = map( s/$searchExpr/$hostName$3\t$5\t$6\t$7/, @newContents );

	    # the above map() call returns an array of success or undef
	    # for each element of @newContents depending on the result of
	    # the substitution (s///)
	    if ( ! grep( /$successExpr/, @result )) {

		# add the new line to the end of the zone file contents if no match succeeded
		push( @newContents, $line );
	    }
	}
    }

    @newContents;
}

# extract the "class C" network address from a reverse domain name
sub networkAddr( $ ) {
    my $reverse_domain = shift;

    my $networkAddr = undef;

    if ( $reverse_domain =~ /(\d+)\.(\d+)\.(\d+)\.in-addr\.arpa/i ) {
	$networkAddr = sprintf( "%d.%d.%d", $3, $2, $1 );
    }

    $networkAddr;
}

# increment the serial number for the zone in the array Ref $zoneData
# this subroutine will work properly until 31 December 2199
# returns the value of the s/// operation with the updated zone in the array Ref
sub incrementSerial ( $$ ) {
    my $w = shift;
    my $zoneData = shift;

    my $returnValue = undef;

    use Time::localtime;

    # Note: this regex matches a serial number with either one or two
    #       digits in the "index" position
    # Back References:
    # $1 initial white space
    # $2 the whole serial number
    # $3 YYYYMMDD, the date part of the serial number
    # $4 the "index" of the serial number (0 - 99 for any given day)
    # $5 rest of the line
    #                     $1  $2   $3       $4        $5
    my $serialExpr = qr/^(\s+)((2[01]\d{6})(\d{1,2}))(.*)$/;

    # year is 1900-based, mon is Zero-based, mday is 1-based. Go figure.
    my $today = sprintf "%4d%02d%02d", ( localtime->year() + 1900 ), ( localtime->mon() + 1 ), localtime->mday();

    foreach my $line ( @$zoneData ) {

	next unless ( $line =~ /$serialExpr/ );

	my $serial = $2;
	my $serialDate = $3;
	my $index = $4;
	my $newSerial = undef;

	# this logic forces a two digit "index" field in the serial number
	if ( $serialDate == $today ) {
	    $newSerial = sprintf "%8d%02d", $serialDate, ( $index + 1 );
	} else {
	    $newSerial = sprintf "%8d%02d", $today, 1;
	}

	$returnValue = ( $line =~ s/$serialExpr/$1$newSerial$5/ );

	last;
    }

    $returnValue;
}

# spread the changes to the other servers in the cluster
# Return 0 if anything goes wrong.
# see http://docs.cpanel.net/twiki/pub/AllDocumentation/TrainingResources/TrainingSlides09/DNS_Cluster_Configuration.pdf
# for more information about /scripts/dnscluster
sub pushChanges( $@ ) {
    my $w = shift;
    my @domains = @_;

    my $command = undef;
    my $returnValue = undef;	# boolean 'true', 'false' (true is good)
    my $exitCode = 0;		# boolean 'true', 'false' (false is good)

    # synchronize each individual domain with the other servers
    foreach my $domain ( @domains ) {

	next unless ( $domain );

	unless ( $exitCode ) {

	    $command = '/scripts/dnscluster synczone ' . $domain;

	    if ( DEBUG ) {
		print
		    $w->p( 'DEBUG: pushChanges: would run system( ', $command, ' )' ),
		    "\n";
	    } else {
		print $w->start_p(), "\n";
		$exitCode = system( $command ),
		print $w->end_p(), "\n";
	    }
	}
    }

    # non-zero $exitCode means one of the commands failed
    # Reload all of the servers if all went will with the synczone calls.
    if ( $exitCode ) {

	print
	    $w->p( { -style => 'color:red;' },
		   'Exception: system( ', $command, ' ) exited with non-zero status: ', $returnValue,
	    ),
	    "\n";
	$returnValue = 0;

    } else {

	# now issue 'rndc reload' to all the DNS-only servers
	# NB: this depends on proper configuration of named.conf and of /etc/rndc.keys.
	# See /usr/local/admin/dns/reload-dns.sh for more details.
	$exitCode = undef;
	$command = '/usr/local/admin/dns/reload-dns.sh';

	if ( -x $command ) {

	    print $w->start_pre(), "\n";
	    $exitCode = system( $command, ( ( DEBUG ) ? '--verbose' : '' ));
	    print $w->end_pre(), "\n";

	    if ( $exitCode == 0 ) {

		$returnValue = 1;

	    } else {

		print
		    $w->p( { -style => 'color:red;' },
			   'Exception: system( ', $command, ' ) exited with non-zero status: ', $returnValue,
		    ),
		    "\n";
		$returnValue = 0;
	    }

	} else {

	    print
		$w->p( { -style => 'color:red;' },
		       'Exception: system( ', $command, ' ) is not executable. Please contact a cPanel administrator',
		),
		"\n";
	    $returnValue = 0;

	}
    }

    $returnValue;
}

=pod

=head1 NAME

addon_bulk-dns-add.cgi

=head1 SYNOPSIS

Generate a list of hostnames and IP addresses in BIND zone file format. Then update the zone file(s) and present them to the user for committing the changes.

=head1 DESCRIPTION

addon_bulk-dns-add.cgi presents a form to the user to enter zone details including a hostname "template" (consisting of a prefix and a starting number), a starting IP address, and an ending IP address. After validating the entries, this script calls itself as the form processor to perform the actual work of generating the zone lines. It calls itself again presenting the user with a colored difference listing between the exisiing zone file and what will replace it. In the last step, the user may commit the zone file. The file is then distributed to the other DNS servers in the cluster using the I</scripts/dnscluster> command.

=head1 FILES

=over 8

=item I</usr/local/cpanel/whostmgr/docroot/cgi/addon_bulk-dns-add.cgi> - the CGI script

=head1 SEE ALSO

=over 8

=item B<WHM Documentation>: http://docs.cpanel.net/twiki/bin/view/SoftwareDevelopmentKit/CreatingWhmPlugins

=back

=cut

__END__
// {
// ----------------------------------------------------------------------
// Javascript form validation routines.
// Author: Stephen Poley
// Additions: David Klann
//
// Simple routines to quickly pick up obvious typos.
// All validation routines return true if executed by an older browser:
// in this case validation must be left to the server.
//
// Update Jun 2005: discovered that reason IE was not setting focus was
// due to an IE timing bug. Added 0.1 sec delay to fix.
//
// Update Oct 2005: minor tidy-up: unused parameter removed
//
// Update Jun 2006: minor improvements to variable names and layout
// ----------------------------------------------------------------------

var nbsp = 160;		// non-breaking space char
var node_text = 3;	// DOM text node-type
var emptyString = /^\s*$/ ;
var global_valfield;	// retain valfield for timer thread

// --------------------------------------------
//                  setfocus
// Delayed focus setting to get around IE bug
// --------------------------------------------
function setFocusDelayed()
{
    global_valfield.focus();
}

function setfocus(valfield)
{
    // save valfield in global variable so value retained when routine exits
	global_valfield = valfield;
    setTimeout( 'setFocusDelayed()', 100 );
}


// --------------------------------------------
//                  msg
// Display warn/error message in HTML element.
// commonCheck routine must have previously been called
// --------------------------------------------
function msg(fld,     // id of element to display message in
             msgtype, // class to give element ("warn" or "error")
             message) // string to display
{
    // setting an empty string can give problems if later set to a
	// non-empty string, so ensure a space present. (For Mozilla and Opera one could
							 // simply use a space, but IE demands something more, like a non-breaking space.)
	var dispmessage;
    if (emptyString.test(message))
	dispmessage = String.fromCharCode(nbsp);
    else
	dispmessage = message;

    var elem = document.getElementById(fld);
    elem.firstChild.nodeValue = dispmessage;

    elem.className = msgtype;   // set the CSS class to adjust appearance of message
}

// --------------------------------------------
//            commonCheck
// Common code for all validation routines to:
// (a) check for older / less-equipped browsers
// (b) check if empty fields are required
// Returns true (validation passed),
//         false (validation failed) or
//         proceed (do not know yet)
// --------------------------------------------
var proceed = 2;

function commonCheck(valfield,   // element to be validated
                     infofield,  // id of element to receive info/error msg
                     required)   // true if required
{
    var retval = proceed;
    var elem = document.getElementById(infofield);

    if (!document.getElementById) {
	retval = true;  // not available on this browser - leave validation to the server
    } else {
	if (elem.firstChild) {
	    if (elem.firstChild.nodeType == node_text) {
		if (emptyString.test(valfield.value)) {
		    if (required) {
			msg (infofield, "error", "ERROR: required");
			setfocus(valfield);
			retval = false;
		    } else {
			msg (infofield, "warn", "");   // OK
			    retval = true;
		    }
		}
	    } else {
		retval = true;  // infofield is wrong type of node
	    }

	} else {
	    retval = true;  // not available on this browser
	}
    }
    return retval;
}

// --------------------------------------------
//            validatePresent
// Validate if something has been entered
// Returns true if so
// --------------------------------------------
function validatePresent(valfield,   // element to be validated
			 infofield ) // id of element to receive info/error msg
{
    var stat = commonCheck (valfield, infofield, true);
    if (stat != proceed) return stat;

    msg (infofield, "warn", "");
    return true;
}

// --------------------------------------------
//             validateIPv4
// Validate an IPv4 address
// Returns true if OK
// --------------------------------------------
function validateIPv4 (valfield,   // element to be validated
		       infofield,   // id of element to receive info/error msg
		       required)    // true if required
{
    var stat = commonCheck (valfield, infofield, required);
    if (stat != proceed) return stat;

    var tfld = valfield.value.replace( /^\s+|\s+$/g, '' );

    if ( /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test( tfld )) {
	var parts = tfld.split(".");

	if ( parseInt(parseFloat( parts[0] )) == 0 ) {
	    msg ( infofield, "error", "ERROR: not a valid IPv4 address (0?)" );
	    setfocus( valfield );
	    return false;
	}

	for ( var i=0; i < parts.length; i++ ) {
	    if ( parseInt(parseFloat( parts[i] )) > 255) {
		msg (infofield, "error", "ERROR: not a valid IPv4 address (255?)");
		setfocus(valfield);
		return false;
	    }
	}
    } else {
	msg (infofield, "error", "ERROR: not a valid IPv4 address (RE)");
	setfocus(valfield);
	return false;
    }

    msg (infofield, "info", "");
    return true;
}

// --------------------------------------------
//             validateIPv6
// Validate an IPv6 address
// Returns true if OK
// --------------------------------------------
function validateIPv6 (valfield,   // element to be validated
		       infofield,   // id of element to receive info/error msg
		       required)    // true if required
{
    var stat = commonCheck (valfield, infofield, required);

    if (stat != proceed) return stat;

    var tfld = valfield.value.replace( /^\s+|\s+$/g, '' );
    // This regex tests IPv6 addresses in all the common formts
	var re = /^\s*((([0-9A-Fa-f]{1,4}:){7}([0-9A-Fa-f]{1,4}|:))|(([0-9A-Fa-f]{1,4}:){6}(:[0-9A-Fa-f]{1,4}|((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})|:))|(([0-9A-Fa-f]{1,4}:){5}(((:[0-9A-Fa-f]{1,4}){1,2})|:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})|:))|(([0-9A-Fa-f]{1,4}:){4}(((:[0-9A-Fa-f]{1,4}){1,3})|((:[0-9A-Fa-f]{1,4})?:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(([0-9A-Fa-f]{1,4}:){3}(((:[0-9A-Fa-f]{1,4}){1,4})|((:[0-9A-Fa-f]{1,4}){0,2}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(([0-9A-Fa-f]{1,4}:){2}(((:[0-9A-Fa-f]{1,4}){1,5})|((:[0-9A-Fa-f]{1,4}){0,3}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(([0-9A-Fa-f]{1,4}:){1}(((:[0-9A-Fa-f]{1,4}){1,6})|((:[0-9A-Fa-f]{1,4}){0,4}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(:(((:[0-9A-Fa-f]{1,4}){1,7})|((:[0-9A-Fa-f]{1,4}){0,5}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:)))(%.+)?\s*$/;

    if ( re.test( tfld )) {
	msg (infofield, "info", "");
	return true;
    } else {
	msg(infofield, "error", "ERROR: not a valid IPv6 address (RE)");
	setfocus(valfield);
	return false;
    }
}

// --------------------------------------------
//             validateHostName
// Validate a hostname
// Returns true if OK
// --------------------------------------------
function validateHostName (valfield,   // element to be validated
			   infofield,  // id of element to receive info/error msg
			   required)   // true if required
{
    var stat = commonCheck (valfield, infofield, required);
    if (stat != proceed) return stat;

    var tfld = valfield.value.replace( /^\s+|\s+$/g, '' );

    if ( ! /^[a-z0-9\.-]+$/.test( tfld )) {
	msg (infofield, "error", "ERROR: not a valid hostname (only [a-z0-9.-])");
	setfocus(valfield);
	return false;
    }

    if (tfld >= 200) {
	msg (infofield, "error", "ERROR: name too long");
	setfocus(valfield);
	return false;
    }

    msg (infofield, "info", "");

    return true;
}

// --------------------------------------------
//             validateBaseAddress
// This is a modification of validateIPv4
// It only looks at three octets
// Returns true if OK
// --------------------------------------------
function validateBaseAddress (valfield,   // element to be validated
			      infofield,   // id of element to receive info/error msg
			      required)    // true if required
{
    var stat = commonCheck (valfield, infofield, required);
    if (stat != proceed) return stat;

    var tfld = valfield.value.replace( /^\s+|\s+$/g, '' );

    if ( /^\d{1,3}\.\d{1,3}\.\d{1,3}$/.test( tfld )) {
	var parts = tfld.split(".");

	if ( parseInt(parseFloat( parts[0] )) == 0 ) {
	    msg ( infofield, "error", "ERROR: not a valid IPv4 network address (0?)" );
	    setfocus( valfield );
	    return false;
	}

	for ( var i=0; i < parts.length; i++ ) {
	    if ( parseInt(parseFloat( parts[i] )) > 255) {
		msg (infofield, "error", "ERROR: not a valid IPv4 octet (255?)");
		setfocus(valfield);
		return false;
	    }
	}
    } else {
	msg (infofield, "error", "ERROR: not a valid IPv4 network address (RE)");
	setfocus(valfield);
	return false;
    }

    msg (infofield, "info", "");
    return true;
}

// --------------------------------------------
//             validateReverseZone
// Validate an in-addr.arpa zone name
// Returns true if OK
// --------------------------------------------
function validateReverseZone (valfield,   // element to be validated
			      infofield,  // id of element to receive info/error msg
			      required)   // true if required
{
    var stat = commonCheck (valfield, infofield, required);
    if (stat != proceed) return stat;

    var tfld = valfield.value.replace( /^\s+|\s+$/g, '' );

    if (tfld >= 24) {
	msg (infofield, "error", "ERROR: name length exceeds 24 characters");
	setfocus(valfield);
	return false;
    }

    if ( ! /^\d+\.\d+\.\d+\.in-addr\.arpa$/.test( tfld )) {
	msg (infofield, "error", "ERROR: not a valid Reverse Zone name ([0-9]+.[0-9]+.[0-9]+.in-addr.arpa)");
	setfocus(valfield);
	return false;
    }

    msg (infofield, "info", "");

    return true;
}

// --------------------------------------------
//             validateNumericRange
// Validate that a number is within a range
// Returns true if OK
// --------------------------------------------
function validateNumericRange (valfield,   // element to be validated
			       infofield,  // id of element to receive info/error msg
			       rmin,       // minimum value in range
			       rmax,       // maximum value in range
			       required)   // true if required
{
    var stat = commonCheck (valfield, infofield, required);
    if (stat != proceed) return stat;

    var tfld = valfield.value.replace( /^\s+|\s+$/g, '' );

    if ( ! /^\d+$/.test(tfld)) {
	msg (infofield, "error", "ERROR: " + tfld + " is not a valid number (only [0-9]+)");
	setfocus(valfield);
	return false;
    }

    if (tfld < rmin || tfld > rmax) {
	msg (infofield, "error", "ERROR: " + tfld + " is outside the valid range");
	setfocus(valfield);
	return false;
    }

    msg (infofield, "info", "");

    return true;
}

// --------------------------------------------
//             toggleVisibility
// toggle visibility of divName based on the
// its present value
// --------------------------------------------
function toggleVisibility ( valfield, divName )
{
    var element = document.getElementById( divName );

    if ( element.style.display == "none" ) {
	// set the element style to "visible"
	    element.style.display = "block";
    } else {
	// set the element style to "invisible"
	    element.style.display = "none";
    }

}
// }
