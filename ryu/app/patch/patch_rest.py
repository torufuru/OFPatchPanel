import logging

import json
from webob import Response

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller import dpset
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_0
from ryu.ofproto import ofproto_v1_2
from ryu.ofproto import ofproto_v1_3
from ryu.lib import ofctl_v1_0
from ryu.lib import ofctl_v1_2
from ryu.lib import ofctl_v1_3
from ryu.app.wsgi import ControllerBase, WSGIApplication, route

patch_instance_name = 'patch_app'

LOG = logging.getLogger('ryu.app.patch.patch_rest')


'''
1. Set port-to-port connectivity

REQUEST
PUT /patch/flow
{
    "dpid": <int>,
    "inport": <int>,
    "outport": <int>,
    # optional
    "mirrorport": <int>
}

RESPONSE
Status Code:
200 OK
400 Bad Request
404 Not Found

2. Delete port-to-port connectivity

REQUEST
DELETE /patch/flow
{
    "dpid": <int>,
    "inport": <int>,
    "outport": <int>,
    # optional
    "mirrorport": <int>
}


RESPONSE
Status Code:
200 OK
400 Bad Request
404 Not Found

2. Get all flows
REQUEST
GET /patch/flow

RESPONSE
Status Code: 200 OK
[
    {
        "dpid": <int>,
        "inport": <int>,
        "outport": <int>,
        #optional
        "mirrorport": <int>
    }
]
'''

class PatchPanel(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_0.OFP_VERSION,
                    ofproto_v1_2.OFP_VERSION,
                    ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {
        'wsgi': WSGIApplication,
        'dpset': dpset.DPSet}

    def __init__(self, *args, **kwargs):
        super(PatchPanel, self).__init__(*args, **kwargs)
        self.dpset = kwargs['dpset']
        wsgi = kwargs['wsgi']
        wsgi.register(PatchController, {patch_instance_name: self})
        self.patch_flows = []  # list of dict(flow)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, MAIN_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        LOG.info('connected datapath: dpid=%d', datapath.id)

    def set_patch_flow(self, req_flow):

        # Check before send flow-mod
        dpid = req_flow.get('dpid')
        dp = self.dpset.get(dpid)
        if dp is None:
            return Response(status=400)
        inport = req_flow.get('inport')
        outport = req_flow.get('outport')
        mirrorport = req_flow.get('mirrorport')
        for flow in self.patch_flows:
            if dpid == flow['dpid'] and inport == flow['inport']:
                LOG.info('Requested inport is already used (dpid:%s, inport:%d)', dpid, inport)
                return Response(status=400)

        new_flow = {
            'match': {
                'in_port': inport
                },
            'actions': [
                {
                    'type': 'OUTPUT',
                    'port': outport
                    }
                ]
            }
        if mirrorport is not None:
            new_flow['actions'].append(
                {
                    'type': 'OUTPUT',
                    'port': mirrorport
                    }
                )

        if dp.ofproto.OFP_VERSION == ofproto_v1_0.OFP_VERSION:
            ofctl_v1_0.mod_flow_entry(dp, new_flow, dp.ofproto.OFPFC_ADD)
            self.patch_flows.append(req_flow)
        elif dp.ofproto.OFP_VERSION == ofproto_v1_2.OFP_VERSION:
            ofctl_v1_2.mod_flow_entry(dp, new_flow, dp.ofproto.OFPFC_ADD)
            self.patch_flows.append(req_flow)
        elif dp.ofproto.OFP_VERSION == ofproto_v1_3.OFP_VERSION:
            ofctl_v1_3.mod_flow_entry(dp, new_flow, dp.ofproto.OFPFC_ADD)
            self.patch_flows.append(req_flow)
        else:
            LOG.info('Unsupported OF protocol')
            return Response(status=501)

        return Response(status=200)

    def delete_patch_flow(self, req_flow):

        # Check before send flow-mod
        dpid = req_flow.get('dpid')
        dp = self.dpset.get(dpid)
        if dp is None:
            return Response(status=400)
        inport = req_flow.get('inport')
        outport = req_flow.get('outport')
        mirrorport = req_flow.get('mirrorport')
        for flow in self.patch_flows:
            if dpid == flow['dpid'] and inport == flow['inport']:
                break
        else:
            LOG.info('Requested inport is not used (dpid:%s, inport:%d)', dpid, inport)
            return Response(status=400)

        del_flow = {
            'match': {
                'in_port': inport
                }
            }
        if dp.ofproto.OFP_VERSION == ofproto_v1_0.OFP_VERSION:
            ofctl_v1_0.mod_flow_entry(dp, del_flow, dp.ofproto.OFPFC_DELETE)
            self.patch_flows.remove(req_flow)
        elif dp.ofproto.OFP_VERSION == ofproto_v1_2.OFP_VERSION:
            ofctl_v1_2.mod_flow_entry(dp, del_flow, dp.ofproto.OFPFC_DELETE)
            self.patch_flows.remove(req_flow)
        elif dp.ofproto.OFP_VERSION == ofproto_v1_3.OFP_VERSION:
            ofctl_v1_3.mod_flow_entry(dp, del_flow, dp.ofproto.OFPFC_DELETE)
            self.patch_flows.remove(req_flow)
        else:
            LOG.debug('Unsupported OF protocol')
            return Response(status=501)

        return Response(status=200)

    def get_patch_flows(self):
        body = json.dumps(self.patch_flows)
        return Response(content_type='application/json',
                        body=body,status=200)


class PatchController(ControllerBase):

    def __init__(self, req, link, data, **config):
        super(PatchController, self).__init__(req, link, data, **config)
        self.patch_app = data[patch_instance_name]

    @route('patch', '/patch/flow', methods=['PUT'])
    def set_patch_flow(self, req, **kwargs):
        LOG.debug("start set_patch_flow")
        patch = self.patch_app
        try:
            flow = eval(req.body)
        except SyntaxError:
            LOG.debug('invalid syntax %s', req.body)
            return Response(status=400)

        result = patch.set_patch_flow(flow)
        return result

    @route('patch', '/patch/flow', methods=['DELETE'])
    def delete_patch_flow(self, req, **kwargs):
        patch = self.patch_app
        try:
            flow = eval(req.body)
        except SyntaxError:
            LOG.debug('invalid syntax %s', req.body)
            return Response(status=400)

        result = patch.delete_patch_flow(flow)
        return result

    @route('patch', '/patch/flow', methods=['GET'])
    def get_patch_flows(self, req, **kwargs):
        patch = self.patch_app
        result = patch.get_patch_flows()
        return result
