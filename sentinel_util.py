#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import os
import sys
import json
import time
import redis
import argparse
import traceback
import threading
import logging, logging.handlers

from kazoo.client import KazooClient


def __initLogger__(level):
    """Init logger"""
    tmp_arr = sys.argv[0].split('.')
    if len(tmp_arr) > 1:
        filename = '.'.join(tmp_arr[0:len(tmp_arr)-1]) + '.log'
    else:
        filename = sys.argv[0] + '.log'
    logdir = os.path.split(os.path.realpath(sys.argv[0]))[0]
    logger = logging.getLogger('sentinel_util')
    logger.setLevel(level)
    fh = logging.handlers.TimedRotatingFileHandler(logdir+os.sep+filename, 'midnight')
    fh.setLevel(logging.DEBUG)
    fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger

def __parseArgument__():
    """Parse arguments"""
    parser = argparse.ArgumentParser(description="Sentinel utils")
    parser.add_argument('-i', '--include', required=True, dest='include')
    parser.add_argument('-z', '--zk', required=True, dest='zk')
    parser.add_argument('-p', '--port', required=True, dest='port')
    parser.add_argument('-c', dest='check', action='store_true')
    parser.add_argument('-m', dest='monitor', action='store_true')
    return parser.parse_args()

class SentinelUtil(threading.Thread):
    """Sentinel utils"""
    zk_path_root = '/zk/redis_sentinel'

    def __init__(self, args, logger, action='check'):
        """__init__
        Init Thread.
        Init include dir.
        Init logger
        """
        threading.Thread.__init__(self)
        self.action = action
        self.args = args
        self.my_list = []
        for fn in os.listdir(self.args.include):
            with open(self.args.include + os.sep + fn) as fh:
                for line in fh:
                    line_data = re.split(' +', line.strip())
                    if line_data[1].upper() == 'MONITOR':
                        self.my_list.append({'name':line_data[2],
                                        'ip':line_data[3],
                                        'port':line_data[4]})
        
        self.logger = logger
        self.zk = KazooClient(hosts=self.args.zk, read_only=True)
        self.zk.start()

    def check(self):
        """Check
        Check all <mymaster> conf are exactly the same with that on zookeeper.
        If not, exit with error
        """
        for my_redis in self.my_list:
            node = '%s/%s/master/master'%(self.zk_path_root, my_redis['name'])
            if self.zk.exists(node):
                val = self.zk.get(node)[0]
                val = json.loads(val)
                if val['addr'] != my_redis['ip'] + ':' + my_redis['port']:
                    self.logger.error("<%s> dismatch zk: %s to conf: %s"\
                                    %(my_redis['name'],
                                        val['addr'],
                                        my_redis['ip'] + ':' + my_redis['port'])
                        )
                    exit(2)
            else:
                self.logger.info('%s not exists, skip'%node)

        exit(0)

    def run(self):
        if self.action == 'subscribe':
            self.subscribe()
        elif self.action == 'refresh':
            self.refresh()

    def subscribe(self):
        """subscribe
        Looping thread. Subscribe from sentinel.
        Udate zookeeper when <mymaster> change.
        Exit when sentinel abort.
        """
        r = redis.StrictRedis(host='127.0.0.1', port=self.args.port, db=0)
        sub = r.pubsub()
        sub.psubscribe("**")
        
        elected = {}
        for msg in sub.listen():
            self.logger.info(msg)

            if msg['channel'] == "+elected-leader":
                # As far as I know, '+elected-leader' message means this sentinel is elected to do failover.
                # So once 'switch-master' message received, we should update zookeeper.
                # Message example: {'pattern': '**', 'type': 'pmessage', 'channel': '+elected-leader', 'data': 'master mymaster 127.0.0.1 6372'}
                msg_data = re.split(' +', msg['data'].strip())
                elected[msg_data[1]] = True
            
            elif msg['channel'] == "+switch-master":
                # The most import msg 'switch-master' means master swithed
                # We update zookeeper immediately
                # Complete failover
                # Message example: {'pattern': '**', 'type': 'pmessage', 'channel': '+switch-master', 'data': 'mymaster 127.0.0.1 6372 127.0.0.1 6371'}
                msg_data = re.split(' +', msg['data'].strip())
                if msg_data[0]in elected and elected[msg_data[0]]:
                    # We are elected to do this failover
                    self.set_master(name=msg_data[0],
                                    old_host=msg_data[1],
                                    old_port=msg_data[2],
                                    host=msg_data[3],
                                    port=msg_data[4])
                    elected[msg_data[0]] = False
                else:
                    # It's other sentinel's duty to do failover
                    pass
            else:
                pass

    def refresh(self):
        """refresh
        Refresh all masters, incase `subscribe` not work correctly
        """
        while True:
            time.sleep(10)
            r = redis.StrictRedis(host='127.0.0.1', port=self.args.port, db=0)
            for m in r.sentinel_masters():
                host, port = r.sentinel_get_master_addr_by_name(m)
                self.logger.debug("<%s> set_master host: %s port: %s"%(m, host, port))
                self.set_master(name=m, host=host, port=port)
                    
    def set_master(self, name, host, port, old_host=None, old_port=None, retry=3):
        try:
            # set master ip & port
            node = '%s/%s/master/master'%(self.zk_path_root, name)
            new_addr = host+':'+ str(port)

            if self.zk.exists(node):
                val = self.zk.get(node)[0]
                val_json = json.loads(val)
                if old_host is not None and old_port is not None:
                    old_addr = old_host+':'+ str(old_port)
                else:
                    old_addr = ''
                if val_json['addr'] == new_addr and val_json['state'] == 'online':
                    self.logger.debug("<%s> set_master called, but current '%s' equals new '%s', so skiped"%(
                        name, val_json['addr'], new_addr))
                else:
                    self.zk.set(node, json.dumps({"addr": new_addr, "state": "online"}, sort_keys=True))
                    self.logger.info("<%s> set master to '%s', former value is '%s'"%(name, new_addr, val))
            else:
                self.logger.warn("<%s> node '%s' not exists, create it"%(name, node))
                self.zk.ensure_path(node)
                self.zk.set(node, json.dumps({"addr": new_addr, "state": "online"}, sort_keys=True))

        except:
            self.logger.debug("<%s> set master exception, will retry\n%s"%(name, traceback.format_exc()))
            # Already retry 3 times, give up
            if retry <= 0:
                self.logger.error("<%s> set master retry 3 times, give up"%(name))
                return
            # Clean up last zookeeper connection
            try:
                self.zk.stop()
            except:
                self.logger.debug("<%s> stop zk except\n%s"%(name, traceback.format_exc()))
            # Sleep 1 second, then retry connect
            time.sleep(1)
            try:
                self.zk = KazooClient(hosts=self.args.zk, read_only=True)
                self.zk.start()
            except:
                self.logger.debug("<%s> reconnect to zk except\n%s"%(name, traceback.format_exc()))
            self.set_master(name=name,
                            host=host,
                            port=port,
                            old_host=old_host,
                            old_port=old_port,
                            retry=retry-1)


if __name__ == "__main__":
    logger = __initLogger__(logging.DEBUG);
    args = __parseArgument__()

    if args.check:
        sentinel = SentinelUtil(args=args, logger=logger)
        sentinel.check()
    elif args.monitor:
        sen_1 = SentinelUtil(args=args, logger=logger, action="subscribe")
        sen_1.start()

        sen_2 = SentinelUtil(args=args, logger=logger, action="refresh")
        sen_2.start()
