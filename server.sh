#!/bin/bash

SCRDIR=$(cd "$(dirname "$0")"; pwd)
cd $SCRDIR

if [[ -f "local_setting.sh" ]];then
    source local_setting.sh
fi

BASE_CONF="base.conf"
REAL_CONF="sentinel.conf"
PORT=$(awk '{if($0 ~ /^port/){print $2;exit;}}' $BASE_CONF)
LOG_FILE="$SCRDIR/sentinel_${PORT}.log"
PID_FILE="$SCRDIR/sentinel_${PORT}.pid"
INCLUDE="$SCRDIR/include/*.conf"
PY_SCRIPT=sentinel_util.py

usage() {
    echo "usage: bash $0 {start | stop | restart}"
}

stop() {
    if [[ -f $PID_FILE ]];then
        echo "pid file [$PID_FILE] found, kill `cat $PID_FILE`"
        cat $PID_FILE | xargs kill && sleep 2
    fi
    nc -z -w 3 127.0.0.1 $PORT && echo "Failed to kill sentinel!" && exit 2
    ps -ef | grep "python $PY_SCRIPT" |grep -v grep | awk '{print $2}' | xargs kill
}

start() {
    redis-sentinel $REAL_CONF
    nohup python $PY_SCRIPT -z $ZOOKEEPER -p $PORT -i include -m &
}

rebuild() {
    python $PY_SCRIPT -z $ZOOKEEPER -p $PORT -i include -c
    [[ $? -ne 0 ]] && echo "ERROR! conf in include differ from zookeeper!" && exit 2

    stop

    [[ -f $REAL_CONF ]] && mv $REAL_CONF ${REAL_CONF}.`date "+%s"`
    cp $BASE_CONF $REAL_CONF
    echo "daemonize yes" >> $REAL_CONF
    echo "logfile '$LOG_FILE'" >> $REAL_CONF
    echo "pidfile '$PID_FILE'" >> $REAL_CONF
    for include_f in `ls $INCLUDE`;do
        echo "include $include_f" >> $REAL_CONF
    done
    echo "" >> $REAL_CONF

    start
}

case "$1" in 
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        stop
        start
        ;;
    rebuild)
        rebuild
        ;;
    *)
        usage
        ;;
esac
