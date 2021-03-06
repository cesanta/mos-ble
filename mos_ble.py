#!/usr/bin/env python
"""

https://github.com/getsenic/gatt-python


mos-ble call method [payload]
mos-ble logcat
mos-ble search

"""
import sys
import json
import struct
import argparse
import logging
import functools

import gatt

log = logging.getLogger(__name__)
log.setLevel(logging.WARNING)

mos_rpc_uuid = '5f6d4f53-5f52-5043-5f53-56435f49445f'
data_uuid = '5f6d4f53-5f52-5043-5f64-6174615f5f5f'
tx_ctl_uuid = '5f6d4f53-5f52-5043-5f74-785f63746c5f'
rx_ctl_uuid = '5f6d4f53-5f52-5043-5f72-785f63746c5f'

def get_argparser():
    parser = argparse.ArgumentParser(description='Mongoose RPC over BLE')
    parser.add_argument(
            "--adapter", type=str, default='hci0')
    parser.add_argument(
            "--address", type=str, required=True,
            help="BLE device address to connet to, required still")
    subparsers = parser.add_subparsers(dest="cmd")
    parser_call = subparsers.add_parser(
            "call", help="Invoke a RPC method")
    parser_call.add_argument(
            "method", type=str)
    parser_call.add_argument(
            "--args", type=str, default="null")
    return parser


get_config_json = json.dumps({
    "method": "Config.Get",
    "src": "python-test",
    "tag": "this is a test",
    "args": None
})

class MosDevice(gatt.Device):
    
    def __init__(self, mac_address, manager):
        super().__init__(mac_address=mac_address, manager=manager)
        self._id = 99
        self._on_ready = None
        self._incoming_len = 0
        self._incoming_data = b''
        self._payload = b''

    
    def _get_id(self):
        self._id += 1
        return self._id

    def run_rpc_call(self, method, args=None):

        frame = {
            "id": self._get_id(),
            "method": method,
            "src": "mos-ble",
            "args": args,
        }
        
        self._payload = json.dumps(frame)

        def _on_ready(self):
            frame_len = len(self._payload)
            log.info("sending %d bytes", frame_len)
            self.tx_ctl_ch.write_value(struct.pack(">I", frame_len))
        
        if (self.is_services_resolved):
            _on_ready(self)
        else:
            self._on_ready = functools.partial(_on_ready, self)
            log.info("prepared for call: %s", self._on_ready)

        self.manager.run()

    def connect_succeeded(self):
        super().connect_succeeded()
        log.info("[%s] Connected", self.mac_address)


    def connect_failed(self, error):
        super().connect_failed(error)
        log.info("[%s] Connection failed: %s", self.mac_address, str(error))

    def disconnect_succeeded(self):
        super().disconnect_succeeded()
        log.info("[%s] Disconnected", self.mac_address)
        self.manager.stop()

    def services_resolved(self):
        super().services_resolved()

        log.debug("[%s] Resolved services", self.mac_address)
        for service in self.services:
            log.debug("[%s]  Service [%s]" % (self.mac_address, service.uuid))
            for characteristic in service.characteristics:
                log.debug("[%s]    Characteristic [%s]" % (self.mac_address, characteristic.uuid))
        
        self.mos_rpc_service = next(
            s for s in self.services
            if s.uuid == mos_rpc_uuid)
        self.data_ch = next(
            c for c in self.mos_rpc_service.characteristics
            if c.uuid == data_uuid)
        self.tx_ctl_ch = next(
            c for c in self.mos_rpc_service.characteristics
            if c.uuid == tx_ctl_uuid)
        self.rx_ctl_ch = next(
            c for c in self.mos_rpc_service.characteristics
            if c.uuid == rx_ctl_uuid)
                
        self.rx_ctl_ch.enable_notifications()

        if callable(self._on_ready):
            log.info("_on_ready")
            self._on_ready()
            
    def characteristic_write_value_succeeded(self, characteristic):
        log.debug("characteristic_write_value_succeeded on %s", characteristic.uuid)
        if characteristic.uuid == tx_ctl_uuid:
            log.debug("sending frame: %s", self._payload)
            self.data_ch.write_value([ord(x) for x in self._payload])
        if characteristic.uuid == data_uuid:
            log.debug("frame sent, waiting for response")
        
    def characteristic_write_value_failed(self, characteristic, error):
        log.warn("characteristic_write_value_failed on %s: %s", characteristic.uuid, error)
        self.manager.stop()

    def characteristic_value_updated(self, characteristic, value):
        if (characteristic.uuid == rx_ctl_uuid):
            in_len = struct.unpack(">I", value)[0]
            if self._incoming_len == 0:
                self._incoming_len = in_len
                if self._incoming_len:
                    log.debug("reading %d bytes ..." % self._incoming_len)
                    self.data_ch.read_value()
            else:
                log.info("got {} for incoming, but already have {}".format(
                         in_len, self._incoming_len))

        if (characteristic.uuid == data_uuid):
            data_len = len(value)
            self._incoming_len -= data_len
            self._incoming_data += value
            log.debug("got {} bytes, {} remaining".format(data_len, self._incoming_len))
            if self._incoming_len > 0:
                self.data_ch.read_value()
            else:
                lfunc = log.debug if self._incoming_len == 0 else log.warn
                lfunc("incoming_len={} actual={}".format
                        (self._incoming_len, len(self._incoming_data)))
                try:
                    data = json.loads(self._incoming_data)
                    if ('result' in data):
                        print(json.dumps(data['result']))
                    elif ('error' in data):
                        print(json.dumps(data['result']))
                    else:
                        log.warn("Seemingly bad response: %s", self._incoming_data)

                except Exception as err:
                    log.exception("BAD JSON: {}".format(err))
                    log.debug("data: %s", self._incoming_data)
                finally:
                    self.manager.stop()

        

def main():
    p = get_argparser()
    args = p.parse_args(sys.argv[1:])
    
    if args.cmd == 'call':
        if args.args:
            args.args = json.loads(args.args)
        manager = gatt.DeviceManager(adapter_name=args.adapter)
        device = MosDevice(mac_address=args.address, manager=manager)
        device.connect()
        device.run_rpc_call(args.method, args.args)

if __name__ == '__main__':
    main()