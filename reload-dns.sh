#!/bin/zsh

############################################################################
#
# call rndc reload on the DNS-only servers
#
############################################################################

dnsOnlyServers=( 10.123.128.11 10.123.128.12 10.123.128.210 10.123.128.212 )
exitVal=

# ensure we can see the executable
RNDC=${RNDC:-$(which rndc)}
RNDC=$(test -x ${RNDC} && echo ${RNDC} || { echo "Cannot find rndc executable, exiting"; exit 3; })

# use getopt to parse the command line args
TEMP=$(getopt -o hv --long html,verbose -n ${0##*/} -- "${@}")
if [ ${?} != 0 ] ; then echo "Terminating..." >&2 ; exit 1 ; fi
# Note the quotes around `$TEMP': they are essential!
eval set -- "${TEMP}"
while :
do
  case "${1}" in
      -h|--html) HTML=1 ; shift ;;
      -v|--verb*) VERBOSE=1 ; shift ;;
      --) shift ; break ;;
      *) echo "Internal error!" ; exit 1 ;;
  esac
done

test "${HTML}" && echo "<pre>"

# reload this host (the master) first
test "${VERBOSE}" && echo "Reloading cpanel (rndc reload) ...\c"
${RNDC} reload

# reload each "DNS-only" server
for server in ${dnsOnlyServers}
do
    test "${VERBOSE}" && echo "Reloading ${server} (rndc -s ${server} reload) ... \c"
    if rndc -s ${server} reload
    then
	exitVal=${?}
    else
	exitVal=${?}
	test "${VERBOSE}" && echo "${HTML:?<b>}Did NOT complete successfully.${HTML:?</b>}"
	# we encountered an error, so proceed no further
	break
    fi
done

test "${HTML}" && echo "</pre>"

exit ${exitVal}
