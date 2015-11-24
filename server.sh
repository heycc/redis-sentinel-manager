#!/bin/bash

SCRDIR=$(cd "$(dirname "$0")"; pwd)
cd $SCRDIR

BASE_CONF="base.conf"
REAL_CONF="sentinel.conf"
PORT=$(awk '{if($0 ~ /^port/){print $2;exit;}}' $BASE_CONF)
LOG_FILE="$SCRDIR/sentinel_${PORT}.log"
PID_FILE="$SCRDIR/sentinel_${PORT}.pid"
INCLUDE="$SCRDIR/include/*.conf"

_stop() {
    if [[ -f $PID_FILE ]];then
        echo "pid file [$PID_FILE] found, kill `cat $PID_FILE`"
        cat $PID_FILE | xargs kill
    fi
}

_start() {
    echo 1
}
_make_conf_file () {
    [[ -f $REAL_CONF ]] && mv $REAL_CONF ${REAL_CONF}.`date "+%s"`
    cp $BASE_CONF $REAL_CONF
    echo "daemonize yes" >> $REAL_CONF
    echo "logfile '$LOG_FILE'" >> $REAL_CONF
    echo "pidfile '$PID_FILE'" >> $REAL_CONF
    for include_f in `ls $INCLUDE`;do
        echo "include $include_f" >> $REAL_CONF
    done
    echo "" >> $REAL_CONF
}

_make_conf_file
