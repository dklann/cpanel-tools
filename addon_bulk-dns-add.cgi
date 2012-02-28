#!/usr/bin/perl
#WHMADDON:init-zone:Bulk DNS Add
#ACLS:create-dns

#      _|_|    _|                        _|                                                    
#    _|    _|      _|  _|_|    _|_|_|  _|_|_|_|  _|  _|_|    _|_|      _|_|_|  _|_|_|  _|_|
#    _|_|_|_|  _|  _|_|      _|_|        _|      _|_|      _|_|_|_|  _|    _|  _|    _|    _|
#    _|    _|  _|  _|            _|_|    _|      _|        _|        _|    _|  _|    _|    _|
#    _|    _|  _|  _|        _|_|_|        _|_|  _|          _|_|_|    _|_|_|  _|    _|    _|

# BEGIN is executed before anything else in the script
# this sets up the search path for library modules
BEGIN {
    unshift @INC,
    '/usr/local/cpanel',
    '/usr/local/cpanel/whostmgr/docroot/cgi',
    '/usr/local/cpanel/cpaddons';
}

use strict;
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

use Net::IP qw(:PROC);

my $debug = 0;

use constant BASE_URL => 'http://localhost:2086/json-api';

sub main();
sub getFormData( $$ );
sub getConfirmation( $$ );
sub processFormData( $$ );
sub authorizedRequest( $$$@ );
sub processJSONresponse( $$$ );

# run it
main;

1;

sub main() {

    my $w = CGI->new();
    my $title = 'Bulk DNS Add';
    my @javaScript = <DATA>;

    Whostmgr::ACLS::init_acls();

    print
	$w->header( -expires => '-1D' ),
	$w->start_html(
	    -title => $title,
	    -script => join( "", @javaScript ),
	);

    Whostmgr::HTMLInterface::defheader( '', '', '/cgi/addon_bulk-dns-add.cgi' );


    if ( $w->param( 'affirmed' )) {
	processFormData( $w, $title );
    } elsif ( $w->param( 'hostname_offset' )) {
	getConfirmation( $w, $title );
    } else {
	getFormData( $w, $title );
    }

    Whostmgr::HTMLInterface::sendfooter();

    print $w->end_html(), "\n";
}

sub getFormData( $$ ) {
    my $w = shift;
    my $title = shift;

    my $returnValue = undef;

    # Ensure they have proper access before doing anything else. See
    # http://docs.cpanel.net/twiki/bin/view/SoftwareDevelopmentKit/CreatingWhmPlugins#Access%20Control
    # for details.
    if ( Whostmgr::ACLS::checkacl( 'create-dns' )) {
	my $ua = LWP::UserAgent->new;

	# $owners is the JSON data structure returned from the query
	# @owners is the array containing a sorted list of unique owners
	my $owners = authorizedRequest( $w, $ua, 'listaccts', ( 'api.version=1', 'searchtype=owner', ));
	my @owners = ();

	# map/reduce: map() gives an array of owner hashes,
	# sort(keys()) gives an array of owners
	if ( $owners ) {
	    @owners = map( { $_->{owner} } @{$owners->{data}->{acct}} );
	    @owners = sort( keys( %{{ map { $_ => 1 } @owners }} ));
	}

	# $domains is the JSON data structure returned from the query
	# @domains is the array containing a sorted list of unique domains
	# @forwardDomains contains "normal" domains, and
	# @inaddrDomains contains "reverse" (in-addr.arpa) domains
	my $domains = authorizedRequest( $w, $ua, 'listzones', ( 'api.version=1', 'searchtype=owner', ));
	my @domains = ();
	my @forwardDomains = ();
	my @inaddrDomains = ();

	if ( $domains ) {

	    # map/reduce: map() gives an array of domain hashes,
	    # keys() gives an array of owners, sort(grep()) drops the
	    # in-addr.arpa zones
	    @domains = map( { $_->{domain} } @{$domains->{data}->{zone}} );
	    @domains = keys( %{{ map { $_ => 1 } @domains }} );
	    @forwardDomains = sort( grep( !/(in-addr|ip6)\.arpa/, @domains ));
	    @inaddrDomains = sort( grep( /(in-addr|ip6)\.arpa/, @domains ));

	    # prepend placeholders for adding a new domain
	    unshift( @forwardDomains, ( '', '-Add New-', ));
	    unshift( @inaddrDomains, ( '', '-Add New-', ));
	} else {
	    @forwardDomains = ( '', '-Add New-' );
	    @inaddrDomains = ( '', '-Add New-' );
	}

	print
	    $w->h1( 'Populate DNS Zone' ), "\n",
	    $w->p( 'Use this form to populate a DNS zone for a reseller.', );

	print
	    $w->start_form(
		-name => 'init_zone',
		-method => 'POST',
		-action => '/cgi/addon_bulk-dns-add.cgi',
	    ), "\n";

	print
	    $w->start_div({ -id => 'outer' });

	print
	    $w->start_table ({ -border => '0' });

	print
	    $w->Tr({ -align => 'left' },
		    $w->th({ -align => 'right' }, 'Owner:&nbsp' ),
		    $w->td(
			$w->popup_menu(
			    -id => 'owner',
			    -name => 'owner',
			    -values => \@owners,
			),
		    ),
		    $w->td({ -id => 'info_owners' }, '' ),
	    ), "\n";

	print $w->end_table (), "\n";

	### forward domains
	print
	    $w->table ({ -border => '0', id => 't1' },
			$w->Tr({ -align => 'left' },
				$w->th({ -align => 'right' }, 'Choose a domain:&nbsp' ),
				$w->td(
				    $w->popup_menu(
					-id => 'existing_forward_domain',
					-name => 'existing_forward_domain',
					-values => \@forwardDomains,
					-onChange => 'processDomain(this, "info_existing_forward_domain", "forward_domain", true)',
				    ),
				),
				$w->td({ -id => 'info_existing_forward_domain' }, '&nbsp;' ),
			),
	    ), "\n";

	# hide this <div> at first (style="display: none")
	# the javascript function processDomain() makes this visible and invisible
	print
	    $w->div({ -id => 'forward_domain', -style => 'display: none' },
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
	    $w->table ({ -border => '0', id => 't1' },
			$w->Tr({ -align => 'left' },
				$w->th({ -align => 'right' }, 'Choose a reverse domain:&nbsp' ),
				$w->td(
				    $w->popup_menu(
					-id => 'existing_reverse_domain',
					-name => 'existing_reverse_domain',
					-values => \@inaddrDomains,
					-onChange => 'processDomain(this, "info_existing_reverse_domain", "reverse_domain", true)',
				    ),
				),
				$w->td({ -id => 'info_existing_reverse_domain' }, '&nbsp;' ),
			),
	    ), "\n";

	# hide this <div> at first (style="display: none")
	# the javascript function processDomain() makes this visible and invisible
	print
	    $w->div({ -id => 'reverse_domain', -style => 'display: none' },
		     $w->table ({ -border => '0', -id => 't2' },
				 $w->Tr({ -align => 'left' },
					 $w->th({ -align => 'right' }, 'New Reverse Domain:&nbsp;' ),
					 $w->td(
					     $w->textfield(
						 -id => 'reverse_domain',
						 -name => 'reverse_domain',
						 -size => '32',
						 -maxlength => '56',
						 -onChange => 'validateHostName(this, "info_reverse_domain", true)'
					     ),
					 ),
					 $w->td({ -id => 'info_reverse_domain' }, '&nbsp;' ),
				 ),
		     ), "\n"
	    );

	# print
	#     $w->start_table ({ -border => '0' } ),
	#     $w->Tr({ -align => 'left' },
	# 	    $w->th({ -align => 'right' }, 'Base Address (first three octets):&nbsp;' ),
	# 	    $w->td(
	# 		$w->textfield(
	# 		    -id => 'ipv4network',
	# 		    -name => 'ipv4network',
	# 		    -size => 11,
	# 		    -maxlength => 11,
	# 		),
	# 	    ),
	# 	    $w->td({ -id => 'info_ipv4network' }, '&nbsp;' ),
	#     ), "\n";

	print
	    $w->Tr({ -align => 'left' },
		    $w->th({ -align => 'right' }, 'Fourth octet start:&nbsp;' ),
		    $w->td(
			$w->textfield(
			    -id => 'ipv4start',
			    -name => 'ipv4start',
			    -size => 3,
			    -maxlength => 3,
			    -onchange  => 'validateNumericRange(this, "info_ipv4start", 1, 255, true)',
			),
		    ),
		    $w->td({ -id => 'info_ipv4start' }, '&nbsp;' ),
	    ), "\n";

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

	print
	    $w->Tr({ -align => 'left' },
		    $w->th({ -align => 'right' }, 'Base hostname:&nbsp' ),
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

	print
	    $w->Tr({ -align => 'left' },
		    $w->th({ -align => 'right' }, 'Starting point for hostname increment:&nbsp' ),
		    $w->td(
			$w->textfield(
			    -id => 'hostname_offset',
			    -name => 'hostname_offset',
			    -size => 3,
			    -maxlength => 3,
			    -onchange  => 'validateNumericRange(this, "info_hostname_offset", 1, 999, true)',
			),
		    ),
		    $w->td({ -id => 'info_hostname_offset' }, '&nbsp;' ),
	    ), "\n";

	print
	    $w->Tr({ -align => 'left' },
		    $w->td(
			$w->checkbox(
			    -id => 'verbose',
			    -name => 'verbose',
			    -value => 'ON',
			    -label => 'Verbose processing',
			),
		    ),
	    ), "\n";

	print
	    $w->Tr({ -align => 'left' },
		    $w->td(
			$w->submit(
			    -name => 'submit',
			    -label => 'Make It So'
			),
		    ),
	    ), "\n";

	print $w->end_form(), "\n";
	print $w->end_table (), "\n";
	print $w->end_div({ id => 'outer' });

    } else {

	print
	    $w->br(), $w->br(),
	    $w->div({ -align => 'center' },
		     $w->h1( 'Permission denied' ),
		     "\n"
	    );

    }
}

sub getConfirmation( $$ ) {
    my $w = shift;
    my $title = shift;

    my $returnValue = undef;

    # Ensure they have proper access before doing anything else. See
    # http://docs.cpanel.net/twiki/bin/view/SoftwareDevelopmentKit/CreatingWhmPlugins#Access%20Control
    # for details.
    if ( Whostmgr::ACLS::checkacl( 'create-dns' )) {

	# get all the parameters from the completed form
	my $owner = $w->param( 'owner' );
	my $existing_forward_domain = $w->param( 'existing_forward_domain' );
	my $forward_domain = $w->param( 'forward_domain' );
	my $ipv4network = $w->param( 'ipv4network' );
	my $ipv4start = $w->param( 'ipv4start' );
	my $ipv4end = $w->param( 'ipv4end' );
	my $hostname_base = $w->param( 'hostname_base' );
	my $hostname_offset = $w->param( 'hostname_offset' );
	my $verbose = $w->param( 'verbose' );

	my $newZone = ( $existing_forward_domain =~ /^-add\s+new-$/i );
	my @bind = ();

	my $ipv4AddressStart = $ipv4network . '.' . $ipv4start;
	my $addrCount = $ipv4start;
	my $hostCount = $hostname_offset;

	my %params = $w->Vars();

	my $ua = LWP::UserAgent->new;

	# they chose an existing domain
	if ( $existing_forward_domain !~ /^-add new-/i ) {
	    $forward_domain = $existing_forward_domain;
	}

	# make the list of IP addresses and hostnames
	# save the full IP address, the domain, and the numbered hostname
	# use an array rather than a hash so we can preserve the order of entries
	for ( $addrCount = $ipv4start; $addrCount <= $ipv4end; $addrCount++ ) {
	    $bind[$addrCount]->{ipv4address} = sprintf( '%s.%d', $ipv4network, $addrCount );
	    $bind[$addrCount]->{forward_domain} = sprintf( '%s.', $forward_domain );
	    $bind[$addrCount]->{hostname} = sprintf( '%s-%d', $hostname_base, $hostCount );
	    $hostCount++;
	}
	if ( $debug || $verbose ) {
	    print
		$w->div({ -id => 'debugzonerecords' },
		    $w->p( 'DEBUG: @bind is:' ), "\n",
		    $w->pre( Dumper( @bind )), "\n",
		);
	}

	# display the new records and await confirmation to proceed
	if ( $newZone ) {
	    print
		$w->h1( { -style => 'color:red' },  'Adding new zone' ),
		$w->p( 'Domain: ', $w->i( $forward_domain )), "\n";
	}
	print
	    $w->start_div({ -id => 'zonerecords' , -style => 'display: block'} ), "\n",
	    $w->start_ul({ -style => 'list-style-type: none; padding: 5px; margin: 5em;' }), "\n";
	foreach my $record ( @bind ) {
	    next unless ( $record->{ipv4address} );
	    print
		$w->li(
		    $record->{ipv4address}, " A ",
		    $record->{hostname} . '.' . $record->{forward_domain},
		),
		"\n";
	}
	print
	    $w->end_ul(),
	    $w->end_div({-id => 'zonerecords' } ),
	    "\n";

	print
	    $w->start_form(
		-name => 'commit_records',
		-method => 'POST',
		-action => '/cgi/addon_bulk-dns-add.cgi',
	    ), "\n";
	print
	    $w->hidden(
		-name => 'affirmed',
		-default => '1',
	    ),
	    "\n";

	# save the parameters from the previous form
	foreach my $p ( sort( keys( %params ))) {
	    next if ( $p =~ /submit/ );
	    print
		$w->hidden(
		    -name => $p,
		    -default => $w->param( $p )
		), "\n";
	}

	print
	    $w->submit(
		-name => 'submit',
		-label => 'Looks Good'
	    ), "\n";

	print $w->end_form(), "\n";

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

sub processFormData( $$ ) {
    my $w = shift;
    my $title = shift;

    my $returnValue = undef;

    # Ensure they have proper access before doing anything else. See
    # http://docs.cpanel.net/twiki/bin/view/SoftwareDevelopmentKit/CreatingWhmPlugins#Access%20Control
    # for details.
    if ( Whostmgr::ACLS::checkacl( 'create-dns' )) {

	# get all the parameters from the completed form
	my $owner = $w->param( 'owner' );
	my $existing_forward_domain = $w->param( 'existing_forward_domain' );
	my $forward_domain = $w->param( 'forward_domain' );
	my $ipv4network = $w->param( 'ipv4network' );
	my $ipv4start = $w->param( 'ipv4start' );
	my $ipv4end = $w->param( 'ipv4end' );
	my $hostname_base = $w->param( 'hostname_base' );
	my $hostname_offset = $w->param( 'hostname_offset' );
	my $verbose = $w->param( 'verbose' );

	my $newZone = ( $existing_forward_domain =~ /^-add\s+new-$/i );
	my @bind = ();

	my $ipv4AddressStart = $ipv4network . '.' . $ipv4start;
	my $addrCount = $ipv4start;
	my $hostCount = $hostname_offset;
	my $response = undef;

	my $ua = LWP::UserAgent->new;

	# they chose an existing domain
	if ( $existing_forward_domain !~ /^-add new-$/i ) {
	    $forward_domain = $existing_forward_domain;
	}

	# make the list of IP addresses and hostnames
	# save the full IP address, the domain, and the numbered hostname
	# use an array rather than a hash so we can preserve the order of entries
	for ( $addrCount = $ipv4start; $addrCount <= $ipv4end; $addrCount++ ) {
	    $bind[$addrCount]->{ipv4Address} = sprintf( '%s.%d', $ipv4network, $addrCount );
	    $bind[$addrCount]->{hostname} = sprintf( '%s-%d', $hostname_base, $hostCount );
	    $hostCount++;
	}
	if ( $debug || $verbose ) {
	    print
		$w->div({ -id => 'debugzonerecords' },
		    $w->p( 'DEBUG: @bind is:' ), "\n",
		    $w->pre( Dumper( @bind )), "\n",
		);
	}

	# create a new zone
	if ( $newZone ) {
	    $response = authorizedRequest( $w, $ua, 'adddns',
					   (
					    'domain=' . $forward_domain,
					    'ip=' . $ipv4AddressStart,
					    'trueowner=' . $owner
					   ));
	}

	if ( ! $newZone || ( $newZone && $response->{metadata}->{result} == 1 )) {

	    # finally, send the boatload off to cPanel,
	    # creating A records and PTR records for each hostname
	    for ( my $count = 0; $count <= $#bind; $count++ ) {
		my $record = $bind[$count];
		next unless ( $record->{ipv4address} );

		$response = undef;

		# create the A record
		$response = authorizedRequest( $w, $ua, 'addzonerecord',
					       (
						'zone=' . $forward_domain,
						'name=' . $record->{hostname} . '.',
						'address=' . $record->{ipv4address},
						'type=A',
					       ));

		# create the PTR record if the A record addition succeeded
		# see http://docs.cpanel.net/twiki/bin/view/SoftwareDevelopmentKit/XmlApiAddZoneRecordAddition
		if ( $response->{metadata}->{result} == 1 ) {
		    $response = authorizedRequest( $w, $ua, 'addzonerecord',
						    'zone=' . Net::IP::ip_reverse( $record->{ipv4network}, 24, 4 ),
						    'name=' . $count,
						    'ptrdname=' . $record->{hostname} . $forward_domain,
						    'type=PTR',
						   );
		    if ( $response->{metadata}->{result} != 1 ) {
			print $w->p( 'ERROR: unable to add PTR record' ), "\n";
			last;
		    }
		} else {
		    print $w->p( 'ERROR: unable to add A record' ), "\n";
		    last;
		}
	    }
	} else {

	    print
		$w->h1( 'ERROR adding zone for domain: ', $forward_domain ),
		$w->p(
		    'Result: ', $response->{metadata}->{result},
		    $w->br(),
		    'Reason: ', $response->{metadata}->{reason},
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

    print $w->pre( Dumper( $URL )), "\n" if ( $debug );

    # see http://docs.cpanel.net/twiki/bin/view/SoftwareDevelopmentKit/ApiAuthentication
    if ( $request = HTTP::Request->new( GET => $URL )) {

	$request->header( Authorization => $authHash );
	$response = $ua->request( $request );
    }

    if ( $response ) {
	print
	    $w->p( '$response from $ua->request():' ),
	    $w->pre( Dumper( $response )), "\n" if ( $debug );

	$jsonRef = processJSONresponse( $w, $action, $response->{'_content'} );
    } else {
	print
	    $w->p( 'ERROR: missing response from $ua->request()' ),
	    $w->pre( Dumper( $response )), "\n";
    }


    $jsonRef;
}

sub processJSONresponse( $$$ ) {
    my $w = shift;
    my $action = shift;
    my $response = shift;

    my $jsonRef = undef;

    if ( $response ) {
	my $json = JSON::PP->new();
	my $completionMessage = undef;

	$jsonRef = $json->decode( $response );

	if ( $jsonRef ) {

	    if ( $jsonRef->{metadata}->{result} == 1 ) {
		$completionMessage = 'Complete: ' . $action . ' succeded';
	    } else {
		$completionMessage = 'ERROR: ' . $action . ' failed';
	    }

	    if ( $w->param('verbose') || $jsonRef->{metadata}->{result} != 1 ) {
		print
		    $w->p(
			$completionMessage,
			$w->br(),
			'Result: ', $jsonRef->{metadata}->{result},
			$w->br(),
			'Reason: ', $jsonRef->{metadata}->{reason},
		    );
	    }
	} else {
	    print $w->p( 'ERROR: unable to decode JSON from ', $response ), "\n";
	}
    } else {
	print $w->p( 'ERROR: received NULL response from adddns request' ), "\n";
    }

    $jsonRef;
}

=pod

=head1 NAME

addon_bulk-dns-add.cgi

=head1 SYNOPSIS

Add a new, or add records to an exising zone for cPanel BIND, automatically filling in the IP addresses and host names based on a template with a starting and ending address.

=head1 DESCRIPTION

addon_bulk-dns-add.cgi presents a form to the user to enter zone details including a hostname "template", a starting IP address, and an ending IP address. After validating the entries, this script calls itself as the form processor to perform the actual work of creating the zone.

=head1 SEE ALSO

=over 8

=item B<WHM Documentation>: http://docs.cpanel.net/twiki/bin/view/SoftwareDevelopmentKit/CreatingWhmPlugins

=item B<init-zone.cgi>, the companion script that performs the data manipulation and loads the zone files

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
//             processDomain
// make the form element in divName visible if the value passed is "-Add New-"
// Returns true if OK
// --------------------------------------------

function processDomain (valfield,   // element to be validated
			infofield,  // id of element to receive info/error msg
			divName,    // id of div to hold new form element
			required)   // true if required
{
    var stat = commonCheck (valfield, infofield, required);
    var returnValue = true;

    if (stat != proceed) return stat;

    var tfld = valfield.value.replace( /^\s+|\s+$/g, '' );

    var divElement = document.getElementById(divName);

    if ( /^-Add New-$/.test( tfld )) {
	// set the element style to "visible"
	    divElement.style.display = "block";
    } else {
	// set the element style to "invisible"
	    divElement.style.display = "none";
    }

    return returnValue;
}

// get affirmation to commit this set of records
function commit ( layerDiv )
{
    var response = confirm( "OK to commit these records?" );
    var returnValue = false;

    if (response == true) {
	returnValue = true;
	alert("You pressed OK!");
	hidelayer( layerDiv );
    } else {
	alert("You pressed Cancel!");
    }

    return returnValue;
}

// toggle visibility of an HTML layer named in layerDiv
function hidelayer ( layerDiv )
{
    var myLayer = document.getElementById(layerDiv).style.display;

    if ( myLayer == "none" ) {
	document.getElementById( layer ).style.display = "block";
    } else {
	document.getElementById( layer ).style.display = "none";
    }
}
// }
