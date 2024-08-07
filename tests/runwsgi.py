# Run a WSGI application in a daemon thread

import threading
import os.path

from . import util

global_stop = False

class Server:
    quiet = False

    def __init__(self, host, port, **options):
        self.options = options
        self.host = host
        self.port = int(port)

    def run(self, handler): # pragma: no cover
        self.srv = self.make_server(handler)
        self.serve()

    def make_server(self, handler):
        from wsgiref.simple_server import make_server, WSGIRequestHandler
        if self.quiet:
            base = self.options.get('handler_class', WSGIRequestHandler)
            class QuietHandler(base):
                def log_request(*args, **kw):
                    pass
            self.options['handler_class'] = QuietHandler
        srv = make_server(self.host, self.port, handler, **self.options)
        return srv

    def serve(self):
        self.srv.serve_forever(poll_interval=0.1)

# http://www.socouldanyone.com/2014/01/bottle-with-ssl.html
# https://github.com/mfm24/miscpython/blob/master/bottle_ssl.py
class SslServer(Server):
    def run(self, handler): # pragma: no cover
        self.srv = self.make_server(handler)

        import ssl
        cert_dir = os.path.join(os.path.dirname(__file__), 'certs')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(
            os.path.join(cert_dir, 'server.crt'),
            keyfile=os.path.join(cert_dir, 'server.key'))
        self.srv.socket = context.wrap_socket(
            self.srv.socket,
            server_side=True)

        self.serve()

def start_bottle_server(app, port, server, **kwargs):
    server_thread = ServerThread(app, port, server, kwargs)
    server_thread.daemon = True
    server_thread.start()

    ok = util.wait_for_network_service(('127.0.0.1', port), 0.1, 10)
    if not ok:
        import warnings
        warnings.warn('Server did not start after 1 second')

    return server_thread.server

class ServerThread(threading.Thread):
    def __init__(self, app, port, server, server_kwargs):
        threading.Thread.__init__(self)
        self.app = app
        self.port = port
        self.server_kwargs = server_kwargs
        self.server = server(host='127.0.0.1', port=self.port, **self.server_kwargs)

    def run(self):
        self.server.run(self.app)

started_servers = {}

def app_runner_setup(*specs):
    '''Returns setup and teardown methods for running a list of WSGI
    applications in a daemon thread.

    Each argument is an (app, port) pair.

    Return value is a (setup, teardown) function pair.

    The setup and teardown functions expect to be called with an argument
    on which server state will be stored.

    Example usage with nose:

    >>> setup_module, teardown_module = \
        runwsgi.app_runner_setup((app_module.app, 8050))
    '''

    def setup(self):
        self.servers = []
        for spec in specs:
            if len(spec) == 2:
                app, port = spec
                kwargs = {}
            else:
                app, port, kwargs = spec
            if port in started_servers:
                assert started_servers[port] == (app, kwargs)
            else:
                server = Server
                if 'server' in kwargs:
                    server = kwargs['server']
                    del kwargs['server']
                elif 'ssl' in kwargs:
                    if kwargs['ssl']:
                        server = SslServer
                    del kwargs['ssl']
                self.servers.append(start_bottle_server(app, port, server, **kwargs))
            started_servers[port] = (app, kwargs)

    def teardown(self):
        return
        for server in self.servers:
            # if no tests from module were run, there is no server to shut down
            if hasattr(server, 'srv'):
                server.srv.shutdown()

    return [setup, teardown]
