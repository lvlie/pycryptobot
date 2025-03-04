import pandas as pd
import argparse, json, logging, math, random, re, sys, urllib3
from datetime import datetime, timedelta
from models.Trading import TechnicalAnalysis
from models.Binance import AuthAPI as BAuthAPI, PublicAPI as BPublicAPI
from models.CoinbasePro import AuthAPI as CBAuthAPI, PublicAPI as CBPublicAPI

# disable insecure ssl warning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# reduce informational logging
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# instantiate the arguments parser
parser = argparse.ArgumentParser(description='Python Crypto Bot using the Coinbase Pro or Binanace API')

# optional arguments
parser.add_argument('--exchange', type=str, help="'coinbasepro', 'binance', 'dummy'")
parser.add_argument('--granularity', type=str, help="coinbasepro: (60,300,900,3600,21600,86400), binance: (1m,5m,15m,1h,6h,1d)")
parser.add_argument('--graphs', type=int, help='save graphs=1, do not save graphs=0')
parser.add_argument('--live', type=int, help='live=1, test=0')
parser.add_argument('--market', type=str, help='coinbasepro: BTC-GBP, binance: BTCGBP etc.')
parser.add_argument('--sellatloss', type=int, help='toggle if bot should sell at a loss')
parser.add_argument('--sellupperpcnt', type=int, help='optionally set sell upper percent limit')
parser.add_argument('--selllowerpcnt', type=int, help='optionally set sell lower percent limit')
parser.add_argument('--sim', type=str, help='simulation modes: fast, fast-sample, slow-sample')
parser.add_argument('--smartswitch', type=int, help='optionally smart switch between 1 hour and 15 minute intervals')
parser.add_argument('--verbose', type=int, help='verbose output=1, minimal output=0')

# parse arguments
args = parser.parse_args()

class PyCryptoBot():
    def __init__(self, exchange='coinbasepro', filename='config.json'):
        self.api_key = ''
        self.api_secret = ''
        self.api_passphrase = ''
        self.api_url = ''

        if args.exchange != None:
            if args.exchange not in [ 'coinbasepro', 'binance', 'dummy' ]:
                raise TypeError('Invalid exchange: coinbasepro, binance')
            else:
                self.exchange = args.exchange
        else:
            self.exchange = exchange

        self.market = 'BTC-GBP'
        self.base_currency = 'BTC'
        self.quote_currency = 'GBP'
        self.granularity = None
        self.is_live = 0
        self.is_verbose = 0
        self.save_graphs = 0
        self.is_sim = 0
        self.sim_speed = 'fast'
        self.sell_upper_pcnt = None
        self.sell_lower_pcnt = None
        self.sell_at_loss = 1
        self.smart_switch = 1
        self.telegram = False

        self._telegram_token = None
        self._telegram_client_id = None

        try:
            with open(filename) as config_file:
                config = json.load(config_file)

                if 'telegram' in config and 'token' in config['telegram'] and 'client_id' in config['telegram']:
                    telegram = config['telegram']

                    p1 = re.compile(r"^\d{1,10}:[A-z0-9-_]{35,35}$")
                    p2 = re.compile(r"^\d{7,10}$")

                    if not p1.match(telegram['token']):
                        print ('Error: Telegram token is invalid')
                    elif not p2.match(telegram['client_id']):
                        print ('Error: Telegram client_id is invalid')
                    else:
                        self.telegram = True
                        self._telegram_token = telegram['token']
                        self._telegram_client_id = telegram['client_id']

                if exchange not in config and 'binance' in config:
                    self.exchange = 'binance'

                if self.exchange == 'coinbasepro' and 'api_key' in config and 'api_secret' in config and ('api_pass' in config or 'api_passphrase' in config) and 'api_url' in config:
                    self.api_key = config['api_key']
                    self.api_secret = config['api_secret']

                    if 'api_pass' in config:
                        self.api_passphrase = config['api_pass']
                    elif 'api_passphrase' in config:
                        self.api_passphrase = config['api_passphrase']

                    self.api_url = config['api_url']

                    if 'config' in config:
                        config = config['config']

                        if 'base_currency' in config:
                            p = re.compile(r"^[A-Z]{3,5}$")
                            if not p.match(config['base_currency']):
                                raise TypeError('Base currency is invalid.')
                            self.base_currency = config['base_currency']

                        if 'cryptoMarket' in config:
                            p = re.compile(r"^[A-Z]{3,5}$")
                            if not p.match(config['cryptoMarket']):
                                raise TypeError('Base currency is invalid.')
                            self.base_currency = config['cryptoMarket']

                        if 'quote_currency' in config:
                            p = re.compile(r"^[A-Z]{3,5}$")
                            if not p.match(config['quote_currency']):
                                raise TypeError('Quote currency is invalid.')
                            self.quote_currency = config['quote_currency']

                        if 'fiatMarket' in config:
                            p = re.compile(r"^[A-Z]{3,5}$")
                            if not p.match(config['fiatMarket']):
                                raise TypeError('Quote currency is invalid.')
                            self.quote_currency = config['fiatMarket']

                        if 'market' in config:
                            p = re.compile(r"^[A-Z]{3,5}\-[A-Z]{3,5}$")
                            if not p.match(config['market']):
                                raise TypeError('Market is invalid.')

                            self.base_currency, self.quote_currency = config['market'].split('-',  2)
                            self.market = config['market']

                        if self.base_currency != '' and self.quote_currency != '':
                            self.market = self.base_currency + '-' + self.quote_currency

                        if 'live' in config:
                            if isinstance(config['live'], int):
                                if config['live'] in [ 0, 1 ]:
                                    self.is_live = config['live']

                        if 'verbose' in config:
                            if isinstance(config['verbose'], int):
                                if config['verbose'] in [ 0, 1 ]:
                                    self.is_verbose = config['verbose']

                        if 'graphs' in config:
                            if isinstance(config['graphs'], int):
                                if config['graphs'] in [ 0, 1 ]:
                                    self.save_graphs = config['graphs']

                        if 'sim' in config:
                            if isinstance(config['sim'], str):
                                if config['sim'] in [ 'slow', 'fast', 'slow-sample', 'fast-sample' ]:
                                    self.is_live = 0
                                    self.is_sim = 1
                                    self.sim_speed = config['sim']

                        if 'sellupperpcnt' in config:
                            if isinstance(config['sellupperpcnt'], int):
                                if config['sellupperpcnt'] > 0 and config['sellupperpcnt'] <= 100:
                                    self.sell_upper_pcnt = int(config['sellupperpcnt'])

                        if 'selllowerpcnt' in config:
                            if isinstance(config['selllowerpcnt'], int):
                                if config['selllowerpcnt'] >= -100 and config['selllowerpcnt'] < 0:
                                    self.sell_lower_pcnt = int(config['selllowerpcnt'])

                        if 'sellatloss' in config:
                            if isinstance(config['sellatloss'], int):
                                if config['sellatloss'] in [ 0, 1 ]:
                                    self.sell_at_loss = config['sellatloss']
                                    if self.sell_at_loss == 0:
                                        self.sell_lower_pcnt = None

                        # backward compatibility
                        if 'nosellatloss' in config:
                            if isinstance(config['nosellatloss'], int):
                                if config['nosellatloss'] in [ 0, 1 ]:
                                    self.sell_at_loss = int(not config['nosellatloss'])
                                    if self.sell_at_loss == 0:
                                        self.sell_lower_pcnt = None

                        if 'smartswitch' in config:
                            if isinstance(config['smartswitch'], int):
                                if config['smartswitch'] in [ 0, 1 ]:
                                    self.smart_switch = config['smartswitch']
                                    if self.smart_switch == 1:
                                        self.smart_switch = 1
                                    else:
                                        self.smart_switch = 0

                        if 'granularity' in config:
                            if isinstance(config['granularity'], int):
                                if config['granularity'] in [ 60, 300, 900, 3600, 21600, 86400 ]:
                                    self.granularity = config['granularity']
                                    self.smart_switch = 0

                elif self.exchange == 'binance' and 'api_key' in config and 'api_secret' in config and 'api_url' in config:
                    self.api_key = config['api_key']
                    self.api_secret = config['api_secret']
                    self.api_url = config['api_url']
                    self.base_currency = 'BTC'
                    self.quote_currency = 'GBP'
                    self.granularity = '1h'

                    if 'binance' not in config:
                        raise Exception('config.json does not contain Binance API keys.')

                    elif 'config' in config['binance']:
                        config = config['binance']['config']

                        if 'base_currency' in config:
                            p = re.compile(r"^[A-Z]{3,5}$")
                            if not p.match(config['base_currency']):
                                raise TypeError('Base currency is invalid.')
                            self.base_currency = config['base_currency']

                        if 'quote_currency' in config:
                            p = re.compile(r"^[A-Z]{3,5}$")
                            if not p.match(config['quote_currency']):
                                raise TypeError('Quote currency is invalid.')
                            self.quote_currency = config['quote_currency']

                        if self.base_currency != '' and self.quote_currency != '':
                            self.market = self.base_currency + self.quote_currency

                        if 'live' in config:
                            if isinstance(config['live'], int):
                                if config['live'] in [0, 1]:
                                    self.is_live = config['live']

                        if 'verbose' in config:
                            if isinstance(config['verbose'], int):
                                if config['verbose'] in [0, 1]:
                                    self.is_verbose = config['verbose']

                        if 'graphs' in config:
                            if isinstance(config['graphs'], int):
                                if config['graphs'] in [0, 1]:
                                    self.save_graphs = config['graphs']

                        if 'sim' in config:
                            if isinstance(config['sim'], str):
                                if config['sim'] in [ 'slow', 'fast', 'slow-sample', 'fast-sample' ]:
                                    self.is_live = 0
                                    self.is_sim = 1
                                    self.sim_speed = config['sim']

                        if 'sellupperpcnt' in config:
                            if isinstance(config['sellupperpcnt'], int):
                                if config['sellupperpcnt'] > 0 and config['sellupperpcnt'] <= 100:
                                    self.sell_upper_pcnt = int(config['sellupperpcnt'])

                        if 'selllowerpcnt' in config:
                            if isinstance(config['selllowerpcnt'], int):
                                if config['selllowerpcnt'] >= -100 and config['selllowerpcnt'] < 0:
                                    self.sell_lower_pcnt = int(config['selllowerpcnt'])

                        if 'sellatloss' in config:
                            if isinstance(config['sellatloss'], int):
                                if config['sellatloss'] in [ 0, 1 ]:
                                    self.sell_at_loss = config['sellatloss']
                                    if self.sell_at_loss == 0:
                                        self.sell_lower_pcnt = None

                        # backward compatibility
                        if 'nosellatloss' in config:
                            if isinstance(config['nosellatloss'], int):
                                if config['nosellatloss'] in [ 0, 1 ]:
                                    self.sell_at_loss = int(not config['nosellatloss'])
                                    if self.sell_at_loss == 0:
                                        self.sell_lower_pcnt = None

                        if 'smartswitch' in config:
                            if isinstance(config['smartswitch'], int):
                                if config['smartswitch'] in [ 0, 1 ]:
                                    self.smart_switch = config['smartswitch']
                                    if self.smart_switch == 1:
                                        self.smart_switch = 1
                                    else:
                                        self.smart_switch = 0

                        if 'granularity' in config:
                            if isinstance(config['granularity'], str):
                                if config['granularity'] in [ '1m', '5m', '15m', '1h', '6h', '1d' ]:
                                    self.granularity = config['granularity']
                                    self.smart_switch = 0

                elif self.exchange == 'coinbasepro' and 'coinbasepro' in config:
                    if 'api_key' in config['coinbasepro'] and 'api_secret' in config['coinbasepro'] and 'api_passphrase' in config['coinbasepro'] and 'api_url' in config['coinbasepro']:
                        self.api_key = config['coinbasepro']['api_key']
                        self.api_secret = config['coinbasepro']['api_secret']
                        self.api_passphrase = config['coinbasepro']['api_passphrase']
                        self.api_url = config['coinbasepro']['api_url']

                        if 'coinbasepro' not in config:
                            raise Exception('config.json does not contain Coinbase Pro API keys.')

                        elif 'config' in config['coinbasepro']:
                            config = config['coinbasepro']['config']

                            if 'base_currency' in config:
                                p = re.compile(r"^[A-Z]{3,5}$")
                                if not p.match(config['base_currency']):
                                    raise TypeError('Base currency is invalid.')
                                self.base_currency = config['base_currency']

                            if 'quote_currency' in config:
                                p = re.compile(r"^[A-Z]{3,5}$")
                                if not p.match(config['quote_currency']):
                                    raise TypeError('Quote currency is invalid.')
                                self.quote_currency = config['quote_currency']

                            if 'market' in config:
                                p = re.compile(r"^[A-Z]{3,5}\-[A-Z]{3,5}$")
                                if not p.match(config['market']):
                                    raise TypeError('Market is invalid.')

                                self.base_currency, self.quote_currency = config['market'].split('-',  2)
                                self.market = config['market']

                            if self.base_currency != '' and self.quote_currency != '':
                                self.market = self.base_currency + '-' + self.quote_currency

                            if 'live' in config:
                                if isinstance(config['live'], int):
                                    if config['live'] in [0, 1]:
                                        self.is_live = config['live']

                            if 'verbose' in config:
                                if isinstance(config['verbose'], int):
                                    if config['verbose'] in [0, 1]:
                                        self.is_verbose = config['verbose']

                            if 'graphs' in config:
                                if isinstance(config['graphs'], int):
                                    if config['graphs'] in [0, 1]:
                                        self.save_graphs = config['graphs']

                            if 'sim' in config:
                                if isinstance(config['sim'], str):
                                    if config['sim'] in ['slow', 'fast', 'slow-sample', 'fast-sample']:
                                        self.is_live = 0
                                        self.is_sim = 1
                                        self.sim_speed = config['sim']

                            if 'sellupperpcnt' in config:
                                if isinstance(config['sellupperpcnt'], int):
                                    if config['sellupperpcnt'] > 0 and config['sellupperpcnt'] <= 100:
                                        self.sell_upper_pcnt = int(config['sellupperpcnt'])

                            if 'selllowerpcnt' in config:
                                if isinstance(config['selllowerpcnt'], int):
                                    if config['selllowerpcnt'] >= -100 and config['selllowerpcnt'] < 0:
                                        self.sell_lower_pcnt = int(config['selllowerpcnt'])

                            if 'sellatloss' in config:
                                if isinstance(config['sellatloss'], int):
                                    if config['sellatloss'] in [ 0, 1 ]:
                                        self.sell_at_loss = config['sellatloss']
                                        if self.sell_at_loss == 0:
                                            self.sell_lower_pcnt = None

                            # backward compatibility
                            if 'nosellatloss' in config:
                                if isinstance(config['nosellatloss'], int):
                                    if config['nosellatloss'] in [ 0, 1 ]:
                                        self.sell_at_loss = int(not config['nosellatloss'])
                                        if self.sell_at_loss == 0:
                                            self.sell_lower_pcnt = None

                            if 'smartswitch' in config:
                                if isinstance(config['smartswitch'], int):
                                    if config['smartswitch'] in [ 0, 1 ]:
                                        self.smart_switch = config['smartswitch']
                                        if self.smart_switch == 1:
                                            self.smart_switch = 1
                                        else:
                                            self.smart_switch = 0

                            if 'granularity' in config:
                                if isinstance(config['granularity'], int):
                                    if config['granularity'] in [60, 300, 900, 3600, 21600, 86400]:
                                        self.granularity = config['granularity']
                                        self.smart_switch = 0

                    else:
                        raise Exception('There is an error in your config.json')

                elif self.exchange == 'binance' and 'binance' in config:
                    if 'api_key' in config['binance'] and 'api_secret' in config['binance'] and 'api_url' in config['binance']:
                        self.api_key = config['binance']['api_key']
                        self.api_secret = config['binance']['api_secret']
                        self.api_url = config['binance']['api_url']
                        self.base_currency = 'BTC'
                        self.quote_currency = 'GBP'
                        self.granularity = '1h'

                        if 'config' in config['binance']:
                            config = config['binance']['config']

                            if 'base_currency' in config:
                                p = re.compile(r"^[A-Z]{3,5}$")
                                if not p.match(config['base_currency']):
                                    raise TypeError('Base currency is invalid.')
                                self.base_currency = config['base_currency']

                            if 'quote_currency' in config:
                                p = re.compile(r"^[A-Z]{3,5}$")
                                if not p.match(config['quote_currency']):
                                    raise TypeError('Quote currency is invalid.')
                                self.quote_currency = config['quote_currency']

                            if self.base_currency != '' and self.quote_currency != '':
                                self.market = self.base_currency + self.quote_currency

                            if 'live' in config:
                                if isinstance(config['live'], int):
                                    if config['live'] in [0, 1]:
                                        self.is_live = config['live']

                            if 'verbose' in config:
                                if isinstance(config['verbose'], int):
                                    if config['verbose'] in [0, 1]:
                                        self.is_verbose = config['verbose']

                            if 'graphs' in config:
                                if isinstance(config['graphs'], int):
                                    if config['graphs'] in [0, 1]:
                                        self.save_graphs = config['graphs']

                            if 'sim' in config:
                                if isinstance(config['sim'], str):
                                    if config['sim'] in ['slow', 'fast', 'slow-sample', 'fast-sample']:
                                        self.is_live = 0
                                        self.is_sim = 1
                                        self.sim_speed = config['sim']

                            if 'sellupperpcnt' in config:
                                if isinstance(config['sellupperpcnt'], int):
                                    if config['sellupperpcnt'] > 0 and config['sellupperpcnt'] <= 100:
                                        self.sell_upper_pcnt = int(config['sellupperpcnt'])

                            if 'selllowerpcnt' in config:
                                if isinstance(config['selllowerpcnt'], int):
                                    if config['selllowerpcnt'] >= -100 and config['selllowerpcnt'] < 0:
                                        self.sell_lower_pcnt = int(config['selllowerpcnt'])

                            if 'sellatloss' in config:
                                if isinstance(config['sellatloss'], int):
                                    if config['sellatloss'] in [ 0, 1 ]:
                                        self.sell_at_loss = config['sellatloss']
                                        if self.sell_at_loss == 0:
                                            self.sell_lower_pcnt = None

                            # backward compatibility
                            if 'nosellatloss' in config:
                                if isinstance(config['nosellatloss'], int):
                                    if config['nosellatloss'] in [ 0, 1 ]:
                                        self.sell_at_loss = int(not config['nosellatloss'])
                                        if self.sell_at_loss == 0:
                                            self.sell_lower_pcnt = None

                            if 'smartswitch' in config:
                                if isinstance(config['smartswitch'], int):
                                    if config['smartswitch'] in [ 0, 1 ]:
                                        self.smart_switch = config['smartswitch']
                                        if self.smart_switch == 1:
                                            self.smart_switch = 1
                                        else:
                                            self.smart_switch = 0

                            if 'granularity' in config:
                                if isinstance(config['granularity'], str):
                                    if config['granularity'] in ['1m', '5m', '15m', '1h', '6h', '1d']:
                                        self.granularity = config['granularity']
                                        self.smart_switch = 0

                    else:
                        raise Exception('There is an error in your config.json')

        except IOError as err:
            now = datetime.today().strftime('%Y-%m-%d %H:%M:%S')
            print (now, err)
        except ValueError as err:
            now = datetime.today().strftime('%Y-%m-%d %H:%M:%S')
            print (now, err)

        if args.market != None:
            if self.exchange == 'coinbasepro':
                p = re.compile(r"^[A-Z]{3,5}\-[A-Z]{3,5}$")
                if not p.match(args.market):
                    raise ValueError('Coinbase Pro market required.')

                self.market = args.market
                self.base_currency, self.quote_currency = args.market.split('-',  2)
            elif self.exchange == 'binance':
                p = re.compile(r"^[A-Z]{6,12}$")
                if not p.match(args.market):
                    raise ValueError('Binance market required.')

                self.market = args.market
                if self.market.endswith('BTC'):
                    self.base_currency = self.market.replace('BTC', '')
                    self.quote_currency = 'BTC'
                elif self.market.endswith('BNB'):
                    self.base_currency = self.market.replace('BNB', '')
                    self.quote_currency = 'BNB'
                elif self.market.endswith('ETH'):
                    self.base_currency = self.market.replace('ETH', '')
                    self.quote_currency = 'ETH'
                elif self.market.endswith('USDT'):
                    self.base_currency = self.market.replace('USDT', '')
                    self.quote_currency = 'USDT'
                elif self.market.endswith('TUSD'):
                    self.base_currency = self.market.replace('TUSD', '')
                    self.quote_currency = 'TUSD'
                elif self.market.endswith('BUSD'):
                    self.base_currency = self.market.replace('BUSD', '')
                    self.quote_currency = 'BUSD'
                elif self.market.endswith('DAX'):
                    self.base_currency = self.market.replace('DAX', '')
                    self.quote_currency = 'DAX'
                elif self.market.endswith('NGN'):
                    self.base_currency = self.market.replace('NGN', '')
                    self.quote_currency = 'NGN'
                elif self.market.endswith('RUB'):
                    self.base_currency = self.market.replace('RUB', '')
                    self.quote_currency = 'RUB'
                elif self.market.endswith('TRY'):
                    self.base_currency = self.market.replace('TRY', '')
                    self.quote_currency = 'TRY'
                elif self.market.endswith('EUR'):
                    self.base_currency = self.market.replace('EUR', '')
                    self.quote_currency = 'EUR'
                elif self.market.endswith('GBP'):
                    self.base_currency = self.market.replace('GBP', '')
                    self.quote_currency = 'GBP'
                elif self.market.endswith('ZAR'):
                    self.base_currency = self.market.replace('ZAR', '')
                    self.quote_currency = 'ZAR'
                elif self.market.endswith('UAH'):
                    self.base_currency = self.market.replace('UAH', '')
                    self.quote_currency = 'UAH'
                elif self.market.endswith('DAI'):
                    self.base_currency = self.market.replace('DAI', '')
                    self.quote_currency = 'DAI'
                elif self.market.endswith('BIDR'):
                    self.base_currency = self.market.replace('BIDR', '')
                    self.quote_currency = 'BIDR'
                elif self.market.endswith('AUD'):
                    self.base_currency = self.market.replace('AUD', '')
                    self.quote_currency = 'AUD'
                elif self.market.endswith('US'):
                    self.base_currency = self.market.replace('US', '')
                    self.quote_currency = 'US'
                elif self.market.endswith('NGN'):
                    self.base_currency = self.market.replace('NGN', '')
                    self.quote_currency = 'NGN'
                elif self.market.endswith('BRL'):
                    self.base_currency = self.market.replace('BRL', '')
                    self.quote_currency = 'BRL'
                elif self.market.endswith('BVND'):
                    self.base_currency = self.market.replace('BVND', '')
                    self.quote_currency = 'BVND'
                elif self.market.endswith('VAI'):
                    self.base_currency = self.market.replace('VAI', '')
                    self.quote_currency = 'VAI'

                if len(self.market) != len(self.base_currency) + len(self.quote_currency):
                    raise ValueError('Binance market error.')

            else:
                if self.market == '' and self.base_currency == '' and self.quote_currency == '':
                    self.market = 'BTC-GBP'
                    self.base_currency = 'BTC'
                    self.quote_currency = 'GBP'

        if args.smartswitch != None:
            if not args.smartswitch in [ '0', '1' ]:
                self.smart_switch = args.smartswitch
                if self.smart_switch == 1:
                    self.smart_switch = 1
                else:
                    self.smart_switch = 0

        if args.granularity != None:
            if self.exchange == 'coinbasepro':
                if not isinstance(int(args.granularity), int):
                    raise TypeError('Invalid granularity.')

                if not int(args.granularity) in [ 60, 300, 900, 3600, 21600, 86400 ]:
                    raise TypeError('Granularity options: 60, 300, 900, 3600, 21600, 86400')
            elif self.exchange == 'binance':
                if not isinstance(args.granularity, str):
                    raise TypeError('Invalid granularity.')

                if not args.granularity in [ '1m', '5m', '15m', '1h', '6h', '1d' ]:
                    raise TypeError('Granularity options: 1m, 5m, 15m, 1h, 6h, 1d')

            self.granularity = args.granularity
            self.smart_switch = 0

        if self.smart_switch == 1 and self.granularity == None:
            if self.exchange == 'coinbasepro':
                self.granularity = 3600
            elif self.exchange == 'binance':
                self.granularity = '1h'

        if args.graphs != None:
            if not args.graphs in [ '0', '1' ]:
                self.save_graphs = args.graphs

        if args.verbose != None:
            if not args.verbose in [ '0', '1' ]:
                self.is_verbose = args.verbose

        if args.live != None:
            if not args.live in [ '0', '1' ]:
                self.is_live = args.live

        if args.sim != None:
            if args.sim == 'slow':
                self.is_sim = 1
                self.sim_speed = 'slow'
                self.is_live = 0
            elif args.sim == 'slow-sample':
                self.is_sim = 1
                self.sim_speed = 'slow-sample'
                self.is_live = 0
            elif args.sim == 'fast':
                self.is_sim = 1
                self.sim_speed = 'fast'
                self.is_live = 0
            elif args.sim == 'fast-sample':
                self.is_sim = 1
                self.sim_speed = 'fast-sample'
                self.is_live = 0

        if args.sellupperpcnt != None:
            if isinstance(args.sellupperpcnt, int):
                if args.sellupperpcnt > 0 and args.sellupperpcnt <= 100:
                    self.sell_upper_pcnt = float(args.sellupperpcnt)

        if args.selllowerpcnt != None:
            if isinstance(args.selllowerpcnt, int):
                if args.selllowerpcnt >= -100 and args.selllowerpcnt < 0:
                    self.sell_lower_pcnt = float(args.selllowerpcnt)

        if args.sellatloss != None:
            if not args.sellatloss in [ '0', '1' ]:
                self.sell_at_loss = args.sellatloss
                if self.sell_at_loss == 0:
                    self.sell_lower_pcnt = None

        if self.exchange == 'binance':
            if len(self.api_url) > 1 and self.api_url[-1] != '/':
                self.api_url = self.api_url + '/'

            valid_urls = [
                'https://api.binance.com/',
                'https://testnet.binance.vision/api/'
            ]

            # validate Binance API
            if self.api_url not in valid_urls:
                raise ValueError('Binance API URL is invalid')

            # validates the api key is syntactically correct
            p = re.compile(r"^[A-z0-9]{64,64}$")
            if not p.match(self.api_key):
                raise TypeError('Binance API key is invalid')

            # validates the api secret is syntactically correct
            p = re.compile(r"^[A-z0-9]{64,64}$")
            if not p.match(self.api_secret):
                raise TypeError('Binance API secret is invalid')

        elif self.exchange == 'coinbasepro':
            if self.api_url[-1] != '/':
                self.api_url = self.api_url + '/'

            valid_urls = [
                'https://api.pro.coinbase.com/'
            ]

            # validate Coinbase Pro API
            if self.api_url not in valid_urls:
                raise ValueError('Coinbase Pro API URL is invalid')

            # validates the api key is syntactically correct
            p = re.compile(r"^[a-f0-9]{32,32}$")
            if not p.match(self.api_key):
                raise TypeError('Coinbase Pro API key is invalid')

            # validates the api secret is syntactically correct
            p = re.compile(r"^[A-z0-9+\/]+==$")
            if not p.match(self.api_secret):
                raise TypeError('Coinbase Pro API secret is invalid')

            # validates the api passphrase is syntactically correct
            p = re.compile(r"^[a-z0-9]{10,11}$")
            if not p.match(self.api_passphrase):
                raise TypeError('Coinbase Pro API passphrase is invalid')

    def getExchange(self):
        return self.exchange

    def getAPIKey(self):
        return self.api_key

    def getAPISecret(self):
        return self.api_secret

    def getAPIPassphrase(self):
        return self.api_passphrase

    def getAPIURL(self):
        return self.api_url

    def getBaseCurrency(self):
        return self.base_currency

    def getQuoteCurrency(self):
        return self.quote_currency

    def getMarket(self):
        return self.market

    def getGranularity(self):
        if self.exchange == 'binance':
            return str(self.granularity)
        elif self.exchange == 'coinbasepro':
            return int(self.granularity)

    def getHistoricalData(self, market, granularity, iso8601start='', iso8601end=''):
        if self.exchange == 'coinbasepro':
            api = CBPublicAPI()
            return api.getHistoricalData(market, granularity, iso8601start, iso8601end)
        elif self.exchange == 'binance':
            api = BPublicAPI()

            if iso8601start != '' and iso8601end != '':
                return api.getHistoricalData(market, granularity, str(datetime.strptime(iso8601start, '%Y-%m-%dT%H:%M:%S.%f').strftime('%d %b, %Y')), str(datetime.strptime(iso8601end, '%Y-%m-%dT%H:%M:%S.%f').strftime('%d %b, %Y')))
            else:
                return api.getHistoricalData(market, granularity)
        else:
            return pd.DataFrame()

    def getSmartSwitch(self):
        return self.smart_switch

    def is1hEMA1226Bull(self):
        try:
            if self.exchange == 'coinbasepro':
                api = CBPublicAPI()
                df_data = api.getHistoricalData(self.market, 3600)
            elif self.exchange == 'binance':
                api = BPublicAPI()
                df_data = api.getHistoricalData(self.market, '1h')
            else:
                return False

            ta = TechnicalAnalysis(df_data)
            ta.addEMA(12)
            ta.addEMA(26)
            df_last = ta.getDataFrame().copy().iloc[-1,:]
            df_last['bull'] = df_last['ema12'] > df_last['ema26']
            return bool(df_last['bull'])
        except Exception:
            return False

    def is1hSMA50200Bull(self):
        try:
            if self.exchange == 'coinbasepro':
                api = CBPublicAPI()
                df_data = api.getHistoricalData(self.market, 3600)
            elif self.exchange == 'binance':
                api = BPublicAPI()
                df_data = api.getHistoricalData(self.market, '1h')
            else:
                return False

            ta = TechnicalAnalysis(df_data)
            ta.addSMA(50)
            ta.addSMA(200)
            df_last = ta.getDataFrame().copy().iloc[-1,:]
            df_last['bull'] = df_last['sma50'] > df_last['sma200']
            return bool(df_last['bull'])
        except Exception:
            return False

    def is6hEMA1226Bull(self):
        try:
            if self.exchange == 'coinbasepro':
                api = CBPublicAPI()
                df_data = api.getHistoricalData(self.market, 21600)
            elif self.exchange == 'binance':
                api = BPublicAPI()
                df_data = api.getHistoricalData(self.market, '6h')
            else:
                return False

            ta = TechnicalAnalysis(df_data)
            ta.addEMA(12)
            ta.addEMA(26)
            df_last = ta.getDataFrame().copy().iloc[-1,:]
            df_last['bull'] = df_last['ema12'] > df_last['ema26']
            return bool(df_last['bull'])
        except Exception:
            return False

    def is6hSMA50200Bull(self):
        try:
            if self.exchange == 'coinbasepro':
                api = CBPublicAPI()
                df_data = api.getHistoricalData(self.market, 21600)
            elif self.exchange == 'binance':
                api = BPublicAPI()
                df_data = api.getHistoricalData(self.market, '6h')
            else:
                return False

            ta = TechnicalAnalysis(df_data)
            ta.addSMA(50)
            ta.addSMA(200)
            df_last = ta.getDataFrame().copy().iloc[-1,:]
            df_last['bull'] = df_last['sma50'] > df_last['sma200']
            return bool(df_last['bull'])
        except Exception:
            return False

    def getTicker(self, market):
        if self.exchange == 'coinbasepro':
            api = CBPublicAPI()
            return api.getTicker(market)
        elif self.exchange == 'binance':
            api = BPublicAPI()
            return api.getTicker(market)
        else:
            return None

    def getTelegramToken(self):
        return self._telegram_token

    def getTelegramClientId(self):
        return self._telegram_client_id

    def isLive(self):
        return self.is_live

    def isVerbose(self):
        return self.is_verbose

    def shouldSaveGraphs(self):
        return self.save_graphs

    def isSimulation(self):
        return self.is_sim

    def isTelegramEnabled(self):
        return self.telegram

    def simuluationSpeed(self):
        return self.sim_speed

    def sellUpperPcnt(self):
        return self.sell_upper_pcnt

    def sellLowerPcnt(self):
        return self.sell_lower_pcnt

    def allowSellAtLoss(self):
        return self.sell_at_loss

    def setGranularity(self, granularity):
        if self.exchange == 'binance' and isinstance(granularity, str) and granularity in [ '1m', '5m', '15m', '1h', '6h', '1d' ]:
            self.granularity = granularity
        elif self.exchange == 'coinbasepro' and isinstance(granularity, int) and granularity in [ 60, 300, 900, 3600, 21600, 86400 ]:
            self.granularity = granularity

    def truncate(self, f, n):
        if not isinstance(f, int) and not isinstance(f, float):
            return 0.0

        if not isinstance(n, int) and not isinstance(n, float):
            return 0.0

        if (f < 0.001):
            if n == 4:
                return '{:.4f}'.format(f)
            elif n == 5:
                return '{:.4f}'.format(f)
            elif n == 6:
                return '{:.4f}'.format(f)
            elif n == 7:
                return '{:.4f}'.format(f)
            elif n >= 8:
                return '{:.4f}'.format(f)

        return math.floor(f * 10 ** n) / 10 ** n

    def compare(self, val1, val2, label='', precision=2):
        if val1 > val2:
            if label == '':
                return str(self.truncate(val1, precision)) + ' > ' + str(self.truncate(val2, precision))
            else:
                return label + ': ' + str(self.truncate(val1, precision)) + ' > ' + str(self.truncate(val2, precision))
        if val1 < val2:
            if label == '':
                return str(self.truncate(val1, precision)) + ' < ' + str(self.truncate(val2, precision))
            else:
                return label + ': ' + str(self.truncate(val1, precision)) + ' < ' + str(self.truncate(val2, precision))
        else:
            if label == '':
                return str(self.truncate(val1, precision)) + ' = ' + str(self.truncate(val2, precision))
            else:
                return label + ': ' + str(self.truncate(val1, precision)) + ' = ' + str(self.truncate(val2, precision))

    def marketBuy(self, market, quote_currency):
        if self.exchange == 'coinbasepro':
            api = CBAuthAPI(self.getAPIKey(), self.getAPISecret(), self.getAPIPassphrase(), self.getAPIURL())
            return api.marketBuy(market, quote_currency)
        elif self.exchange == 'binance':
            api = BAuthAPI(self.getAPIKey(), self.getAPISecret(), self.getAPIURL())
            return api.marketBuy(market, quote_currency)
        else:
            return None

    def marketSell(self, market, base_currency):
        if self.exchange == 'coinbasepro':
            api = CBAuthAPI(self.getAPIKey(), self.getAPISecret(), self.getAPIPassphrase(), self.getAPIURL())
            return api.marketSell(market, base_currency)
        elif self.exchange == 'binance':
            api = BAuthAPI(self.getAPIKey(), self.getAPISecret(), self.getAPIURL())
            return api.marketSell(market, base_currency)
        else:
            return None

    def setMarket(self, market):
        if self.exchange == 'binance':
            p = re.compile(r"^[A-Z]{6,12}$")
            if p.match(market):
                self.market = market

                if self.market.endswith('BTC'):
                    self.base_currency = self.market.replace('BTC', '')
                    self.quote_currency = 'BTC'
                elif self.market.endswith('BNB'):
                    self.base_currency = self.market.replace('BNB', '')
                    self.quote_currency = 'BNB'
                elif self.market.endswith('ETH'):
                    self.base_currency = self.market.replace('ETH', '')
                    self.quote_currency = 'ETH'
                elif self.market.endswith('USDT'):
                    self.base_currency = self.market.replace('USDT', '')
                    self.quote_currency = 'USDT'
                elif self.market.endswith('TUSD'):
                    self.base_currency = self.market.replace('TUSD', '')
                    self.quote_currency = 'TUSD'
                elif self.market.endswith('BUSD'):
                    self.base_currency = self.market.replace('BUSD', '')
                    self.quote_currency = 'BUSD'
                elif self.market.endswith('DAX'):
                    self.base_currency = self.market.replace('DAX', '')
                    self.quote_currency = 'DAX'
                elif self.market.endswith('NGN'):
                    self.base_currency = self.market.replace('NGN', '')
                    self.quote_currency = 'NGN'
                elif self.market.endswith('RUB'):
                    self.base_currency = self.market.replace('RUB', '')
                    self.quote_currency = 'RUB'
                elif self.market.endswith('TRY'):
                    self.base_currency = self.market.replace('TRY', '')
                    self.quote_currency = 'TRY'
                elif self.market.endswith('EUR'):
                    self.base_currency = self.market.replace('EUR', '')
                    self.quote_currency = 'EUR'
                elif self.market.endswith('GBP'):
                    self.base_currency = self.market.replace('GBP', '')
                    self.quote_currency = 'GBP'
                elif self.market.endswith('ZAR'):
                    self.base_currency = self.market.replace('ZAR', '')
                    self.quote_currency = 'ZAR'
                elif self.market.endswith('UAH'):
                    self.base_currency = self.market.replace('UAH', '')
                    self.quote_currency = 'UAH'
                elif self.market.endswith('DAI'):
                    self.base_currency = self.market.replace('DAI', '')
                    self.quote_currency = 'DAI'
                elif self.market.endswith('BIDR'):
                    self.base_currency = self.market.replace('BIDR', '')
                    self.quote_currency = 'BIDR'
                elif self.market.endswith('AUD'):
                    self.base_currency = self.market.replace('AUD', '')
                    self.quote_currency = 'AUD'
                elif self.market.endswith('US'):
                    self.base_currency = self.market.replace('US', '')
                    self.quote_currency = 'US'
                elif self.market.endswith('NGN'):
                    self.base_currency = self.market.replace('NGN', '')
                    self.quote_currency = 'NGN'
                elif self.market.endswith('BRL'):
                    self.base_currency = self.market.replace('BRL', '')
                    self.quote_currency = 'BRL'
                elif self.market.endswith('BVND'):
                    self.base_currency = self.market.replace('BVND', '')
                    self.quote_currency = 'BVND'
                elif self.market.endswith('VAI'):
                    self.base_currency = self.market.replace('VAI', '')
                    self.quote_currency = 'VAI'

                if len(self.market) != len(self.base_currency) + len(self.quote_currency):
                    raise ValueError('Binance market error.')

        elif self.exchange == 'coinbasepro':
            p = re.compile(r"^[A-Z]{3,5}\-[A-Z]{3,5}$")
            if p.match(market):
                self.market = market
                self.base_currency, self.quote_currency = market.split('-',  2)

        return (self.market, self.base_currency, self.quote_currency)

    def setLive(self, flag):
        if isinstance(flag, int) and flag in [0, 1]:
            self.is_live = flag

    def setNoSellAtLoss(self, flag):
        if isinstance(flag, int) and flag in [0, 1]:
            self.sell_at_loss = flag

    def startApp(self, account, last_action=''):
        print('--------------------------------------------------------------------------------')
        print('|                             Python Crypto Bot                                |')
        print('--------------------------------------------------------------------------------')

        if self.isVerbose() == 1:
            txt = '           Market : ' + self.getMarket()
            print('|', txt, (' ' * (75 - len(txt))), '|')
            if self.exchange == 'coinbasepro':
                txt = '      Granularity : ' + str(self.getGranularity()) + ' seconds'
            elif self.exchange == 'binance':
                txt = '      Granularity : ' + str(self.getGranularity())
            print('|', txt, (' ' * (75 - len(txt))), '|')
            print('--------------------------------------------------------------------------------')

        if self.isLive() == 1:
            txt = '         Bot Mode : LIVE - live trades using your funds!'
        else:
            txt = '         Bot Mode : TEST - test trades using dummy funds :)'

        print('|', txt, (' ' * (75 - len(txt))), '|')

        txt = '      Bot Started : ' + str(datetime.now())
        print('|', txt, (' ' * (75 - len(txt))), '|')
        print('================================================================================')

        if self.sellUpperPcnt() != None:
            txt = '       Sell Upper : ' + str(self.sellUpperPcnt()) + '%'
            print('|', txt, (' ' * (75 - len(txt))), '|')

        if self.sellLowerPcnt() != None:
            txt = '       Sell Lower : ' + str(self.sellLowerPcnt()) + '%'
            print('|', txt, (' ' * (75 - len(txt))), '|')

        if self.allowSellAtLoss() == False:
            txt = '     Sell At Loss : ' + str(self.allowSellAtLoss())
            print('|', txt, (' ' * (75 - len(txt))), '|')

        if self.sellUpperPcnt() != None or self.sellLowerPcnt() != None or self.allowSellAtLoss() == False:
            print('================================================================================')

        # if live
        if self.isLive() == 1:
            if self.getExchange() == 'binance':
                if last_action == 'SELL'and account.getBalance(self.getQuoteCurrency()) < 0.001:
                    raise Exception('Insufficient available funds to place sell order: ' + str(account.getBalance(self.getQuoteCurrency())) + ' < 0.1 ' + self.getQuoteCurrency() + "\nNote: A manual limit order places a hold on available funds.")
                elif last_action == 'BUY'and account.getBalance(self.getBaseCurrency()) < 0.001:
                    raise Exception('Insufficient available funds to place buy order: ' + str(account.getBalance(self.getBaseCurrency())) + ' < 0.1 ' + self.getBaseCurrency() + "\nNote: A manual limit order places a hold on available funds.")

            elif self.getExchange() == 'coinbasepro':
                if last_action == 'SELL'and account.getBalance(self.getQuoteCurrency()) < 50:
                    raise Exception('Insufficient available funds to place buy order: ' + str(account.getBalance(self.getQuoteCurrency())) + ' < 50 ' + self.getQuoteCurrency() + "\nNote: A manual limit order places a hold on available funds.")
                elif last_action == 'BUY'and account.getBalance(self.getBaseCurrency()) < 0.001:
                    raise Exception('Insufficient available funds to place sell order: ' + str(account.getBalance(self.getBaseCurrency())) + ' < 0.1 ' + self.getBaseCurrency() + "\nNote: A manual limit order places a hold on available funds.")

        # run the first job immediately after starting
        if self.isSimulation() == 1:
            if self.simuluationSpeed() in [ 'fast-sample', 'slow-sample' ]:
                tradingData = pd.DataFrame()

                attempts = 0
                while len(tradingData) != 300 and attempts < 10:
                    endDate = datetime.now() - timedelta(hours=random.randint(0,8760 * 3)) # 3 years in hours
                    startDate = endDate - timedelta(hours=300)
                    tradingData = self.getHistoricalData(self.getMarket(), self.getGranularity(), startDate.isoformat(), endDate.isoformat())
                    attempts += 1

                if len(tradingData) != 300:
                    raise Exception('Unable to retrieve 300 random sets of data between ' + str(startDate) + ' and ' + str(endDate) + ' in ' + str(attempts) + ' attempts.')

                startDate = str(startDate.isoformat())
                endDate = str(endDate.isoformat())
                txt = '   Sampling start : ' + str(startDate)
                print('|', txt, (' ' * (75 - len(txt))), '|')
                txt = '     Sampling end : ' + str(endDate)
                print('|', txt, (' ' * (75 - len(txt))), '|')
                print('================================================================================')

            else:
                tradingData = self.getHistoricalData(self.getMarket(), self.getGranularity())

            return tradingData