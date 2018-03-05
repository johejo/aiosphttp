from flask import Flask, Response, request

from aiosphttp.downloader import Downloader

app = Flask(__name__)


@app.route('/proxy')
def proxy():

    hosts = request.args.get('hosts').split(',')
    split_size = int(request.args.get('split_size', 10**6))
    duplicate_request = bool(request.args.get('duplicate_request', True))
    allow_redirects = bool(request.args.get('allow_redirects', True))
    close_bad_session = bool(request.args.get('close_bad_session', True))
    initial_delay_prediction = bool(request.args.
                                    get('initial_delay_prediction', True))
    threshold = int(request.args.get('threshold', 20))
    initial_delay_coefficient = float(request.args.
                                      get('initial_delay_coefficient', 10))

    d = Downloader(urls=hosts, split_size=split_size,
                   duplicate_request=duplicate_request,
                   allow_redirects=allow_redirects,
                   close_bad_session=close_bad_session,
                   initial_delay_prediction=initial_delay_prediction,
                   initial_delay_coefficient=initial_delay_coefficient,
                   threshold=threshold)

    return Response(d.generator(), mimetype='application/octet-stream')


if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True, port=8080)
