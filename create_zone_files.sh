#!/bin/zsh

# this provides the shell function strftime() and the variable ${EPOCHSECONDS}
zmodload zsh/datetime

base="${ROOT:-/}usr/local/admin/dns"
tmpNamedConf="${base}/tmpNamedConf"
tmpZoneFiles="${base}/zonefiles"
tmpcPanelZoneFiles="${base}/cPanelZoneFiles"
varNamed=${ROOT:-/}var/named
servers=( 10.123.128.11 10.123.128.12 10.123.128.211 10.123.128.212 )

verbose=${VERBOSE:-1}
debug=${DEBUG:-1}

# temporary file for a cpanel zone list
cPanelZoneList=$(mktemp)
trap "rm -f ${cPanelZoneList}; exit" 0 1 2

test -d ${tmpZoneFiles} || sudo mkdir ${tmpZoneFiles}
test -d ${tmpcPanelZoneFiles} || sudo mkdir ${tmpcPanelZoneFiles}

# see klann@wins.net for an explanation of this wget(1) call
# Note: the Basic Auth string needs to be updated when the WHM root password changes
(( verbose == 1 )) && echo "; -- Creating ${cPanelZoneList} --"
wget -q \
    --output-document=- \
    --header='Authorization: Basic cm9vdDpxbzpMeT02dDg1MjJeSE17aipVeFwjKSgtWWs8bmJ5WUw6QDdWIU5RcSsnRSZmbU87KTRKTyglNSp4amxFNlo=' \
    'http://localhost:2086/json-api/listzones?api.version=1&searchtype=owner' |
  tr '{' '\012' | tr -d '}' > ${cPanelZoneList}
(( verbose == 1 )) && echo "; -- Created ${cPanelZoneList} --"

todaysDate=$(strftime "%Y%m%d" ${EPOCHSECONDS})
mtime=${EPOCHSECONDS}		# this is used in the first comment line in the cPanel zone file
lastSerial=$(cat ${base}/last_serial)
serialDate=$(echo ${lastSerial} | cut -c0-8)
if [ "${serialDate}" = "${todaysDate}" ]; then
    newSerial=$(( lastSerial + 1 ))
else 
    newSerial="${todaysDate}01"
fi

add_forward=${ADD_FORWARD:-1}
kill_commented=${KILL_COMMENTED:-1}
reload_named=${RELOAD_NAMED:-0}

(( verbose == 1 )) && echo "; -- new serial number: ${newSerial}"

# get a fresh copy of the authoritative named.conf
sudo ssh root@bucky.airstreamcomm.net 'cat /var/named/named.conf' >! ${tmpNamedConf}

IFS="
"

if (( add_forward == 1 )); then

    # the sed command drops the entry for the root zone (".")
    for line in $(grep "^zone" ${tmpNamedConf} | sed '1d')
    do
	### Get zone & file names

	# this
	#zone=$(echo "${line}" | cut -d"\"" -f2 | cut -d"\"" -f1)
	# becomes
	zone=${${line#*\"}%\"*}

	(( verbose == 1 )) && echo "\n; -------------------   ${zone}   ---------------------"

	# we only need to add the zone to cPanel if it is not already registered
	if grep --quiet ${zone} ${cPanelZoneList}; then
	    echo "Zone ${zone} is already registered with cPanel. Not calling /scripts/add_dns."
	else
	    if (( debug )); then
		echo "DEBUG: /scripts/add_dns --domain ${zone} --reseller root --ip 64.33.128.80"
	    else
		/scripts/add_dns --domain ${zone} --reseller root --ip 64.33.128.80
	    fi
	fi

	# find the name of the file containing the zone
	# the grep(1) returns a line of the form <WHITESPACE>file "primary/rev.208.157.190";
	# the second line below strips everything but the filename
	file=$(grep -A2 "^zone \"${zone}\"" ${tmpNamedConf} | grep 'file "primary/')
	file=${${file##*/}%\"*}

	# get the zone file name from the cPanel configuration
	# this depends on the zone having been in cPanel at the start of this run
	cPanelZoneFile=$(grep "zonefile.*:\"${zone}\"" ${cPanelZoneList} | cut -d\" -f4)

	(( verbose == 1 )) && echo "; -- Our zone file: ${file}, cPanel zone file: ${cPanelZoneFile}"
	test -n "${cPanelZoneFile}" || { echo "ERROR: missing cPanelZoneFile"; exit; }

	### Get contents of zone file on bucky and dump into local zone file

	# Skip to the next zone if the zone file does not exist on bucky
	sudo ssh root@bucky.airstreamcomm.net "/usr/local/admin/dnsscripts/catfileif.sh ${file}" > ${tmpZoneFiles}/${zone}
	if grep "doesn't exist" ${tmpZoneFiles}/${zone}; then
	    echo "\n Cannot find zone file ${file} for zone ${zone} on bucky, skipping!"
	    rm -f ${tmpZoneFiles}/${zone}
	    continue
	fi

	### Update the zone serial number

	# note that the following tr(1) command deletes all whitespace
	# characters (including CR, NL, TAB, etc.)
	serial=$(pcregrep -o '^\s+20[01]\d{7}' ${tmpZoneFiles}/${zone} | tr -d '[[:space:]]')

	sed --regexp-extended --in-place --expression="s/^(\s+)${serial}/\1${newSerial}/" ${tmpZoneFiles}/${zone}

	### And while we are at it, change brutus.bright.net to ns2.airstreamcomm.net
	if pcregrep --quiet -i '\s+IN\s+NS\s+brutus\.bright\.net\.\s*$' ${tmpZoneFiles}/${zone}; then
	    (( verbose )) && echo "; -- Replacing brutus.bright.net NS record"
	    sed --regexp-extended --in-place --expression='s/(\s+IN\s+NS\s+)brutus\.bright\.net\.\s*$/\1ns2.airstreamcomm.net./i' ${tmpZoneFiles}/${zone}
	fi

	### Insert cPanel specific lines

	# create the new zone file with a name and comments that cPanel will enjoy
	cat > ${tmpcPanelZoneFiles}/${cPanelZoneFile} <<EOF
; cPanel first:11.28.83-STABLE_51164 (update_time):${mtime} Cpanel::ZoneFile::VERSION:1.3 hostname:cpanel.airstreamcomm.net latest:11.30.3.5
; Zone file for ${zone}
$(cat ${tmpZoneFiles}/${zone})
EOF

	### Move the zone file into place
	if (( debug )); then
	    echo "DEBUG: mv ${tmpcPanelZoneFiles}/${cPanelZoneFile} ${varNamed}"
	else
	    sudo mv ${tmpcPanelZoneFiles}/${cPanelZoneFile} ${varNamed}
	    sudo /bin/chown named: ${varNamed}/${cPanelZoneFile}
	fi

	(( verbose == 1 )) && echo "\n; -- Completed ${zone}"

    done
fi

if (( kill_commented )); then

    echo

    for line in $(grep "//zone" ${tmpNamedConf})
    do
	zone=${${line#*\"}%\"*}

	if grep --quiet "^zone \"${zone}\"" ${tmpNamedConf}; then
	    echo " * ${zone} exists, not removing"
	else

	    # check if the zone is in cPanel
	    if grep --quiet ${zone} ${cPanelZoneList}; then

		# get the zone file name from the cPanel configuration
		cPanelZoneFile=$(grep "zonefile.*:\"${zone}\"" ${cPanelZoneList} | cut -d\" -f4)

		if (( debug )); then
		    echo "DEBUG: /scripts/killdns ${zone}"
		    if [ -f ${varNamed}/${cPanelZoneFile} ]
		    then
			echo "DEBUG: rm -f ${varNamed}/${cPanelZoneFile}"
		    fi
		else
		    if [ -f ${varNamed}/${cPanelZoneFile} ]
		    then
			/scripts/killdns ${zone}
		    else
			echo " - ${varNamed}/${cPanelZoneFile} does not exist!"
		    fi
		fi
	    fi
	fi
    done

fi

if (( debug )); then
    echo "echo ${newSerial} > ${base}/last_serial"
else
    echo ${newSerial} > ${base}/last_serial
fi

### Rsync to the other cPanel DNS servers
for server in ${servers}; do
    if (( debug )); then
        sudo rsync -av --dry-run --exclude='cache/' --exclude='data/' ${varNamed}/ root@${server}:${varNamed}
    else
        sudo rsync -a --exclude='cache/' --exclude='data/' ${varNamed}/ root@${server}:${varNamed}
    fi
done

if (( reload_named )); then
    sudo service named reload
    for server in ${servers}; do
	sudo ssh root@${server} "service named reload"
    done
fi

exit
