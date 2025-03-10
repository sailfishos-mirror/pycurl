#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vi:ts=4:et

from . import localhost
import pycurl
import pytest
import unittest
import select
import sys
import flaky

from . import appmanager
from . import util

setup_module_1, teardown_module_1 = appmanager.setup(('app', 8380))
setup_module_2, teardown_module_2 = appmanager.setup(('app', 8381))
setup_module_3, teardown_module_3 = appmanager.setup(('app', 8382))

def setup_module(mod):
    setup_module_1(mod)
    setup_module_2(mod)
    setup_module_3(mod)

def teardown_module(mod):
    teardown_module_3(mod)
    teardown_module_2(mod)
    teardown_module_1(mod)

@flaky.flaky(max_runs=3)
class MultiSocketSelectTest(unittest.TestCase):
    def setUp(self):
        self.m = pycurl.CurlMulti()
        self.m.handles = []

    def tearDown(self):
        for c in self.m.handles:
            self.m.remove_handle(c)
            c.close()
        self.m.close()

    @pytest.mark.skipif(sys.platform == 'win32', reason='https://github.com/pycurl/pycurl/issues/819')
    def test_multi_socket_select(self):
        sockets = set()
        timeout = 0

        urls = [
            # we need libcurl to actually wait on the handles,
            # and initiate polling.
            # thus use urls that sleep for a bit.
            'http://%s:8380/short_wait' % localhost,
            'http://%s:8381/short_wait' % localhost,
            'http://%s:8382/short_wait' % localhost,
        ]

        socket_events = []

        # socket callback
        def socket(event, socket, multi, data):
            if event == pycurl.POLL_REMOVE:
                #print("Remove Socket %d"%socket)
                sockets.remove(socket)
            else:
                if socket not in sockets:
                    #print("Add socket %d"%socket)
                    sockets.add(socket)
            socket_events.append((event, multi))

        # init
        m = self.m
        m.setopt(pycurl.M_SOCKETFUNCTION, socket)
        for url in urls:
            c = util.DefaultCurl()
            # save info in standard Python attributes
            c.url = url
            c.body = util.BytesIO()
            c.http_code = -1
            m.handles.append(c)
            # pycurl API calls
            c.setopt(c.URL, c.url)
            c.setopt(c.WRITEFUNCTION, c.body.write)
            m.add_handle(c)

        # get data
        #num_handles = len(m.handles)

        while (pycurl.E_CALL_MULTI_PERFORM==m.socket_all()[0]):
            pass

        timeout = m.timeout()
        if timeout == -1:
            timeout = 1000

        # timeout might be -1, indicating that all work is done
        # XXX make sure there is always work to be done here?
        while timeout >= 0:
            (rr, wr, er) = select.select(sockets,sockets,sockets,timeout/1000.0)
            socketSet = set(rr+wr+er)
            if socketSet:
                for s in socketSet:
                    while True:
                        (ret,running) = m.socket_action(s,0)
                        if ret!=pycurl.E_CALL_MULTI_PERFORM:
                            break
            else:
                (ret,running) = m.socket_action(pycurl.SOCKET_TIMEOUT,0)
            if running==0:
                break

        for c in m.handles:
            # save info in standard Python attributes
            c.http_code = c.getinfo(c.HTTP_CODE)

        # at least in and remove events per socket
        assert len(socket_events) >= 6, 'Less than 6 socket events: %s' % repr(socket_events)

        # print result
        for c in m.handles:
            self.assertEqual('success', c.body.getvalue().decode())
            self.assertEqual(200, c.http_code)

            # multi, not curl handle
            self.check(pycurl.POLL_IN, m, socket_events)
            self.check(pycurl.POLL_REMOVE, m, socket_events)

    def check(self, event, multi, socket_events):
        for event_, multi_ in socket_events:
            if event == event_ and multi == multi_:
                return
        assert False, '%d %s not found in socket events' % (event, multi)
