#!/bin/sh
dir="/tmp"
if [ -f $dir/rev.tmp ]; then
	rm -r $dir/rev.tmp
fi
if [ -f $dir/zone.tmp ]; then
	rm -r $dir/zone.tmp
fi

echo "This script will build a new rev file and the zone file"
echo "To break out of this script, type 'CTRL-C"
echo " "
echo -e "Input the first 3 octets ( ex: 64.33.128 ): \c"
read firstset
echo " "
echo -e "Input the numbers in the 4th octet of the starting IP address: \c"
read firstfourth
echo " " 
echo -e "Input the numbers in the 4th octet of the ending IP address: \c"
read lastfourth
echo " "
echo -e "Input the domain (ex: win.bright.net, durand.k12.wi.us): \c"
read domain
echo " "
echo -e "Input the host name without the number, (ex: mil-cs, som-cs, dhs, etc.): \c" 
read host
echo " "
echo -e "Input the number of the first machine/modem (usually 1): \c"
read number
echo " "
echo "Your first address will be: "$firstset.$firstfourth
echo "Your first domain will be: "$host"-"$number.$domain
echo -e "If this is correct type 'y', if no, start over by typing 'n': \c"
read ans
echo -e "Should the header information be appended to the output files? 'y/n': \c"
read ans2

if [ -f $dir/rev.$firstset ]; then
	rm -r $dir/rev.$firstset
fi
if [ -f $dir/zone.$firstset ]; then
	rm -r $dir/zone.$firstset
fi

if [ $ans = "y" ]; then

   if [ $ans2 = "y" ]; then
	echo '$TTL 43200' >> $dir/rev.$firstset
        echo ";----------------------------------------------------------------------------" >> $dir/rev.$firstset
        echo "@       in      soa     ns1.airstreamcomm.net. hostmaster.airstreamcomm.net. (" >> $dir/rev.$firstset
        echo "                  2009090301 ; serial YYMMDDR" >> $dir/rev.$firstset
       	echo "                  86400   ; refresh" >> $dir/rev.$firstset
       	echo "                  14400   ; retry" >> $dir/rev.$firstset
        echo "                  3600000 ; expire" >> $dir/rev.$firstset
       	echo "                  86400 ) ; minimum" >> $dir/rev.$firstset
       	echo "          IN	NS	ns1.airstreamcomm.net." >> $dir/rev.$firstset
        echo "          IN	NS	ns2.airstreamcomm.net." >> $dir/rev.$firstset
        echo ";----------------------------------------------------------------------------" >> $dir/rev.$firstset

       while [ $firstfourth -le $lastfourth ];
       do 
 	echo $firstfourth"	IN	PTR	"$host"-"$number"."$domain"." >> $dir/rev.$firstset
	echo $host-$number"	IN	A	"$firstset.$firstfourth >> $dir/zone.$firstset
 	firstfourth=`expr $firstfourth + 1`  
 	number=`expr $number + 1`
       done
       echo "Your rev file is in $dir/rev.$firstset and your zone file is in $dir/zone.$firstset"

   else

       while [ $firstfourth -le $lastfourth ];
       do 
 	echo $firstfourth"	IN	PTR	"$host"-"$number"."$domain"." >> $dir/rev.$firstset
	echo $host-$number"	IN	A	"$firstset.$firstfourth >> $dir/zone.$firstset
 	firstfourth=`expr $firstfourth + 1`  
 	number=`expr $number + 1`
       done
       echo "Your rev file is in $dir/rev.$firstset and your zone file is in $dir/zone.$firstset"
   fi

else
	sh /usr/local/admin/bin/zonemaker.sh
fi
