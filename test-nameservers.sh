#!/bin/zsh

zmodload zsh/datetime
zmodload zsh/stat
zmodload zsh/mathfunc

base=${BASE:-${ROOT:-/}var/tmp}
namedConf=${NAMED_CONF:-$(mktemp -p ${base} named.conf.XXXXXX)}

master=64.33.128.10
slaves=( 10.123.128.80 10.123.128.11 10.123.128.12 10.123.128.211 10.123.128.212 )

masterAXFR=$(mktemp -p ${base} master-axfr.XXXXXX)

slaveAXFR=$(mktemp -p ${base} slave-axfr.XXXXXX)

# clean up after ourselves
trap "rm -f ${namedConf} ${masterAXFR} ${slaveAXFR}; exit" 0 1 2

sudo scp root@bucky.airstreamcomm.net:/etc/named.conf ${namedConf}

# note: ${zones} is an array
zones=( $(grep "^zone" ${namedConf} | sed '1d' | cut -d"\"" -f2 | sort) )

startTime=${EPOCHSECONDS}

for domain in ${zones}
do
    rm -f ${masterAXFR} ${slaveAXFR}

    print "; ---------------   start ${domain}   ---------------"

    # get the zone from the master
    dig +nocmd +nostats @${master} ${domain} axfr > ${masterAXFR}

    # flag errors and move on
    if fgrep --quiet 'Transfer failed.' ${masterAXFR}
    then
	print "; -- ${domain}"
	cat ${masterAXFR}
	continue
    fi

    for slave in ${slaves}
    do
	rm -f ${slaveAXFR}

        # get the zone from the master
	dig +nocmd +nostats @${slave} ${domain} axfr > ${slaveAXFR}

        # flag errors and move on
	if fgrep --quiet 'Transfer failed.' ${slaveAXFR}
	then
	    printf "; -- %s -- %s: %s\n" ${slave} ${domain} "$(cat ${slaveAXFR})"
	    continue
	fi

	# compare the zone transfer results with the master
	if ! diff -q -i --ignore-all-space --ignore-matching-lines='IN[[:space:]][[:space:]]*SOA' ${masterAXFR} ${slaveAXFR} 2>& 1 > /dev/null
	then
	    print "; -- differences between ${master} and ${slave} for ${domain}"
	    diff -i --ignore-all-space --ignore-matching-lines='IN[[:space:]][[:space:]]*SOA' ${masterAXFR} ${slaveAXFR}
	    print ";\n"
	else
	    print "; -- ${domain}: ${slave} matches ${master}"
	fi
    done

    print "; ---------------    end  ${domain}   ---------------"
done

endTime=${EPOCHSECONDS}

print $(strftime "Start: %Y-%m-%d %T" ${startTime})
print $(strftime "Start: %Y-%m-%d %T" ${endTime})
print $(strftime "Duration: %T" $((endTime - startTime)) )
