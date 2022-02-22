#!/usr/bin/env python3

"""
Credit: https://github.com/sharsil/mailcat
"""


class Mailcat:
    name = "MailCat Email Discovery"
    description = "Discover Email Addresses associated with a Username or Phrase."
    originTypes = {'Email Address', 'Phrase', 'Social Media Handle'}
    resultTypes = {'Email Address'}
    parameters = {'Route traffic over Tor': {'description': 'This option dictates whether traffic should be routed '
                                                            'over the Tor network. Requires an active Tor service on '
                                                            'the host the resolution runs on.\nNOTE: This option is '
                                                            'incompatible with the "Route traffic over Proxy" option. '
                                                            'If both are selected, Tor will not be used.',
                                             'type': 'SingleChoice',
                                             'value': {'Yes', 'No'},
                                             'default': 'No'
                                             },
                  'Route traffic over Proxy': {'description': 'This option dictates whether traffic should be routed '
                                                              'over a proxy host. Please specify the proxy to route '
                                                              'traffic through in the following format:\n'
                                                              'https://user:pass@1.2.3.4:8080\nAlternatively, put '
                                                              '"NONE" (no quotes) in the input box if you don\'t want '
                                                              'to route traffic through a proxy.\nNOTE: This option is '
                                                              'incompatible with the "Route traffic over Tor" option. '
                                                              'If both are selected, Tor will not be used.',
                                               'type': 'String',
                                               'value': '',
                                               'default': 'NONE'
                                               }}

    def resolution(self, entityJsonList, parameters):
        import aiohttp
        import asyncio
        import base64
        import datetime
        import json
        import logging
        import random
        import aiosmtplib
        import string as s
        import re
        from time import sleep
        from typing import Dict, List
        import dns.resolver
        from requests_html import AsyncHTMLSession  # type: ignore
        from aiohttp_socks import ProxyConnector

        from multiprocessing import Process, Queue
        from queue import Empty

        return_results_queue = Queue()
        return_results = []

        uaLst = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 "
            "Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.77 "
            "Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.106 "
            "Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 "
            "Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 "
            "Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.101 "
            "Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/91.0.4472.114 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/91.0.4472.77 Safari/537.36 "
        ]

        # logging.basicConfig(format='%(message)s')
        logger = logging.getLogger('mailcat')
        logger.setLevel(100)

        def randstr(num):
            return ''.join(random.sample((s.ascii_lowercase + s.ascii_uppercase + s.digits), num))

        def sleeper(sList, s_min, s_max):
            for ind in sList:
                if sList.index(ind) < (len(sList) - 1):
                    sleep(random.uniform(s_min, s_max))

        def via_proxy(proxy_str):
            def via():
                connector = ProxyConnector.from_url(proxy_str)
                session = aiohttp.ClientSession(connector=connector)
                return session

            return via

        def via_tor():
            connector = ProxyConnector.from_url('socks5://127.0.0.1:9050')
            session = aiohttp.ClientSession(connector=connector)
            return session

        def simple_session():
            return aiohttp.ClientSession()

        async def code250(mailProvider, target):
            target = target
            providerLst = []

            error = ''

            randPref = ''.join(random.sample(s.ascii_lowercase, 6))
            fromAddress = "{}@{}".format(randPref, mailProvider)
            targetMail = "{}@{}".format(target, mailProvider)

            records = dns.resolver.Resolver().resolve(mailProvider, 'MX')
            mxRecord = records[0].exchange
            mxRecord = str(mxRecord)

            try:
                server = aiosmtplib.esmtp.ESMTP(timeout=10)
                # server.set_debuglevel(0)

                await server.connect(hostname=mxRecord)
                await server.helo()
                await server.mail(fromAddress)
                code, message = await server.rcpt(targetMail)

                if code == 250:
                    providerLst.append(targetMail)

                message_str = message.lower()
                if 'ban' in message_str or 'denied' in message_str:
                    error = message_str

            except aiosmtplib.errors.SMTPRecipientRefused:
                pass
            except Exception as e:
                logger.error(e, exc_info=True)
                error = str(e)

            return providerLst, error

        async def gmail(target, req_session_fun) -> Dict:
            result = {}
            gmailChkLst, error = await code250("gmail.com", target)
            if gmailChkLst:
                result["Google"] = gmailChkLst[0]

            await asyncio.sleep(0)
            return result, error

        async def yandex(target, req_session_fun) -> Dict:
            result = {}
            yaAliasesLst = ["yandex.by",
                            "yandex.kz",
                            "yandex.ua",
                            "yandex.com",
                            "ya.ru"]
            yaChkLst, error = await code250("yandex.ru", target)
            if yaChkLst:
                yaAliasesLst = ['{}@{}'.format(target, yaAlias) for yaAlias in yaAliasesLst]
                yaMails = list(set(yaChkLst + yaAliasesLst))
                result["Yandex"] = yaMails

            await asyncio.sleep(0)
            return result, error

        async def proton(target, req_session_fun) -> Dict:
            result = {}

            protonLst = ["protonmail.com", "protonmail.ch", "pm.me"]
            protonSucc = []
            sreq = req_session_fun()

            protonURL = "https://mail.protonmail.com/api/users/available?Name={}".format(target)

            headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:60.0) Gecko/20100101 Firefox/60.0",
                       "Accept": "application/vnd.protonmail.v1+json",
                       "Accept-Language": "en-US,en;q=0.5",
                       "Accept-Encoding": "gzip, deflate",
                       "Referer": "https://mail.protonmail.com/create/new?language=en",
                       "x-pm-appversion": "Web_3.16.19",
                       "x-pm-apiversion": "3",
                       "Cache-Control": "no-cache",
                       "Pragma": "no-cache",
                       "DNT": "1", "Connection": "close"}

            try:

                chkProton = await sreq.get(protonURL, headers=headers, timeout=3)

                async with chkProton:
                    if chkProton.status == 409:
                        resp = await chkProton.json()
                        exists = resp['Error']
                        if exists == "Username already used":
                            protonSucc = ["{}@{}".format(target, protodomain) for protodomain in protonLst]

            except Exception as e:
                logger.error(e, exc_info=True)

            if protonSucc:
                result["Proton"] = protonSucc

            await sreq.close()

            return result

        async def mailRu(target, req_session_fun) -> Dict:
            result = {}

            mailRU = ["mail.ru", "bk.ru", "inbox.ru", "list.ru", "internet.ru"]
            mailRuSucc = []
            sreq = req_session_fun()

            for maildomain in mailRU:
                try:
                    headers = {'User-Agent': random.choice(uaLst)}
                    mailruMail = "{}@{}".format(target, maildomain)
                    data = {'email': mailruMail}

                    chkMailRU = await sreq.post('https://account.mail.ru/api/v1/user/exists', headers=headers,
                                                data=data, timeout=5)

                    async with chkMailRU:
                        if chkMailRU.status == 200:
                            resp = await chkMailRU.json()
                            exists = resp['body']['exists']
                            if exists:
                                mailRuSucc.append(mailruMail)

                except Exception as e:
                    logger.error(e, exc_info=True)

                sleep(random.uniform(0.5, 2))

            if mailRuSucc:
                result["MailRU"] = mailRuSucc

            await sreq.close()

            return result

        async def rambler(target, req_session_fun) -> Dict:  # basn risk
            result = {}

            ramblerMail = ["rambler.ru", "lenta.ru", "autorambler.ru", "myrambler.ru", "ro.ru", "rambler.ua"]
            ramblerSucc = []
            sreq = req_session_fun()

            for maildomain in ramblerMail:

                try:
                    targetMail = "{}@{}".format(target, maildomain)

                    # reqID = ''.join(random.sample((s.ascii_lowercase + s.ascii_uppercase + s.digits), 20))
                    reqID = randstr(20)
                    userAgent = random.choice(uaLst)
                    ramblerChkURL = "https://id.rambler.ru:443/jsonrpc"

                    #            "Referer": "https://id.rambler.ru/login-20/mail-registration?back=https%3A%2F%2Fmail.rambler.ru%2F&rname=mail&param=embed&iframeOrigin=https%3A%2F%2Fmail.rambler.ru",

                    headers = {"User-Agent": userAgent,
                               "Referer": "https://id.rambler.ru/login-20/mail-registration?utm_source=head"
                                          "&utm_campaign=self_promo&utm_medium=header&utm_content=mail&rname=mail"
                                          "&back=https%3A%2F%2Fmail.rambler.ru%2F%3Futm_source%3Dhead%26utm_campaign%3Dself_promo%26utm_medium%3Dheader%26utm_content%3Dmail"
                                          "&param=embed&iframeOrigin=https%3A%2F%2Fmail.rambler.ru&theme=mail-web",
                               "Content-Type": "application/json",
                               "Origin": "https://id.rambler.ru",
                               "X-Client-Request-Id": reqID}

                    ramblerJSON = {"method": "Rambler::Id::login_available", "params": [{"login": targetMail}],
                                   "rpc": "2.0"}
                    ramblerChk = await sreq.post(ramblerChkURL, headers=headers, json=ramblerJSON, timeout=5)

                    async with ramblerChk:
                        if ramblerChk.status == 200:
                            try:
                                resp = await ramblerChk.json(content_type=None)
                                exist = resp['result']['profile']['status']
                                if exist == "exist":
                                    ramblerSucc.append(targetMail)
                                    # print("[+] Success with {}".format(targetMail))
                                # else:
                                #    print("[-]".format(ramblerChk.text))
                            except KeyError as e:
                                logger.error(e, exc_info=True)

                    sleep(random.uniform(4, 6))  # don't reduce

                except Exception as e:
                    logger.error(e, exc_info=True)

            if ramblerSucc:
                result["Rambler"] = ramblerSucc

            await sreq.close()

            return result

        async def tuta(target, req_session_fun) -> Dict:
            result = {}

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36'}

            tutaMail = ["tutanota.com", "tutanota.de", "tutamail.com", "tuta.io", "keemail.me"]
            tutaSucc = []
            sreq = req_session_fun()

            for maildomain in tutaMail:

                try:

                    targetMail = "{}@{}".format(target, maildomain)
                    tutaURL = "https://mail.tutanota.com/rest/sys/mailaddressavailabilityservice?_body="

                    tutaCheck = await sreq.get(
                        '{}%7B%22_format%22%3A%220%22%2C%22mailAddress%22%3A%22{}%40{}%22%7D'.format(tutaURL, target,
                                                                                                     maildomain),
                        headers=headers, timeout=5)

                    async with tutaCheck:
                        if tutaCheck.status == 200:
                            resp = await tutaCheck.json()
                            exists = resp['available']

                            if exists == "0":
                                tutaSucc.append(targetMail)

                    sleep(random.uniform(2, 4))

                except Exception as e:
                    logger.error(e, exc_info=True)

            if tutaSucc:
                result["Tutanota"] = tutaSucc

            await sreq.close()

            return result

        async def yahoo(target, req_session_fun) -> Dict:
            result = {}

            yahooURL = "https://login.yahoo.com:443/account/module/create?validateField=yid"
            yahooCookies = {"B": "10kh9jteu3edn&b=3&s=66", "AS": "v=1&s=wy5fFM96"}  # 13 8
            # yahooCookies = {"B": "{}&b=3&s=66".format(randstr(13)), "AS": "v=1&s={}".format(randstr(8))} # 13 8
            headers = {"User-Agent": random.choice(uaLst),
                       "Accept": "*/*", "Accept-Language": "en-US,en;q=0.5", "Accept-Encoding": "gzip, deflate",
                       "Referer": "https://login.yahoo.com/account/create?.src=ym&.lang=en-US&.intl=us&.done=https%3A%2F%2Fmail.yahoo.com%2Fd&authMechanism=primary&specId=yidReg",
                       "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                       "X-Requested-With": "XMLHttpRequest",
                       "DNT": "1", "Connection": "close"}

            # yahooPOST = {"specId": "yidReg", "crumb": randstr(11), "acrumb": randstr(8), "yid": target} # crumb: 11, acrumb: 8
            yahooPOST = {"specId": "yidReg", "crumb": "bshN8x9qmfJ", "acrumb": "wy5fFM96", "yid": target}
            sreq = req_session_fun()

            try:
                yahooChk = await sreq.post(yahooURL, headers=headers, cookies=yahooCookies, data=yahooPOST, timeout=5)

                body = await yahooChk.text()
                if '"IDENTIFIER_EXISTS"' in body:
                    result["Yahoo"] = "{}@yahoo.com".format(target)

            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def outlook(target, req_session_fun) -> Dict:
            result = {}
            liveSucc = []
            sreq = AsyncHTMLSession(loop=asyncio.get_event_loop())
            headers = {"User-Agent": random.choice(uaLst)}
            liveLst = ["outlook.com", "hotmail.com"]
            url_template = 'https://signup.live.com/?username={}@{}&uaid=f746d3527c20414d8c86fd7f96613d85&lic=1'

            for maildomain in liveLst:
                try:
                    liveChk = await sreq.get(url_template.format(target, maildomain), headers=headers)
                    await liveChk.html.arender(sleep=10)

                    if "suggLink" in liveChk.html.html:
                        liveSucc.append("{}@{}".format(target, maildomain))

                except Exception as e:
                    logger.error(e, exc_info=True)

            if liveSucc:
                result["Live"] = liveSucc

            await sreq.close()

            return result

        async def zoho(target, req_session_fun) -> Dict:
            result = {}

            headers = {
                "User-Agent": "User-Agent: Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.7113.93 Safari/537.36",
                "Referer": "https://www.zoho.com/",
                "Origin": "https://www.zoho.com"
            }

            zohoURL = "https://accounts.zoho.com:443/accounts/validate/register.ac"
            zohoPOST = {"username": target, "servicename": "VirtualOffice", "serviceurl": "/"}
            sreq = req_session_fun()

            try:
                zohoChk = await sreq.post(zohoURL, headers=headers, data=zohoPOST, timeout=10)

                async with zohoChk:
                    if zohoChk.status == 200:
                        # if "IAM.ERROR.USERNAME.NOT.AVAILABLE" in zohoChk.text:
                        #    print("[+] Success with {}@zohomail.com".format(target))
                        resp = await zohoChk.json()
                        if resp['error']['username'] == 'This username is taken':
                            result["Zoho"] = "{}@zohomail.com".format(target)
                            # print("[+] Success with {}@zohomail.com".format(target))
            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def lycos(target, req_session_fun) -> Dict:
            result = {}

            lycosURL = "https://registration.lycos.com/usernameassistant.php?validate=1&m_AID=0&t=1625674151843&m_U={}&m_PR=27&m_SESSIONKEY=4kCL5VaODOZ5M5lBF2lgVONl7tveoX8RKmedGRU3XjV3xRX5MqCP2NWHKynX4YL4".format(
                target)

            headers = {
                "User-Agent": "User-Agent: Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.7113.93 Safari/537.36",
                "Referer": "https://registration.lycos.com/register.php?m_PR=27&m_E=7za1N6E_h_nNSmIgtfuaBdmGpbS66MYX7lMDD-k9qlZCyq53gFjU_N12yVxL01F0R_mmNdhfpwSN6Kq6bNfiqQAA",
                "X-Requested-With": "XMLHttpRequest"}
            sreq = req_session_fun()

            try:
                lycosChk = await sreq.get(lycosURL, headers=headers, timeout=10)

                async with lycosChk:
                    if lycosChk.status == 200:
                        resp = await lycosChk.text()
                        if resp == "Unavailable":
                            result["Lycos"] = "{}@lycos.com".format(target)
            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def eclipso(target, req_session_fun) -> Dict:  # high ban risk + false positives after
            result = {}

            eclipsoSucc = []

            eclipsoLst = ["eclipso.eu",
                          "eclipso.de",
                          "eclipso.at",
                          "eclipso.ch",
                          "eclipso.be",
                          "eclipso.es",
                          "eclipso.it",
                          "eclipso.me",
                          "eclipso.nl",
                          "eclipso.email"]

            headers = {'User-Agent': random.choice(uaLst),
                       'Referer': 'https://www.eclipso.eu/signup/tariff-5',
                       'X-Requested-With': 'XMLHttpRequest'}
            sreq = req_session_fun()

            for maildomain in eclipsoLst:
                try:
                    targetMail = "{}@{}".format(target, maildomain)

                    eclipsoURL = "https://www.eclipso.eu/index.php?action=checkAddressAvailability&address={}".format(
                        targetMail)
                    chkEclipso = await sreq.get(eclipsoURL, headers=headers, timeout=5)

                    async with chkEclipso:
                        if chkEclipso.status == 200:
                            resp = await chkEclipso.text()
                            if '>0<' in resp:
                                eclipsoSucc.append(targetMail)
                except Exception as e:
                    logger.error(e, exc_info=True)

                sleep(random.uniform(2, 4))

            if eclipsoSucc:
                result["Eclipso"] = eclipsoSucc

            await sreq.close()

            return result

        async def posteo(target, req_session_fun) -> Dict:
            result = {}

            posteoLst = [
                "posteo.af",
                "posteo.at",
                "posteo.be",
                "posteo.ca",
                "posteo.ch",
                "posteo.cl",
                "posteo.co",
                "posteo.co.uk",
                "posteo.com.br",
                "posteo.cr",
                "posteo.cz",
                "posteo.de",
                "posteo.dk",
                "posteo.ee",
                "posteo.es",
                "posteo.eu",
                "posteo.fi",
                "posteo.gl",
                "posteo.gr",
                "posteo.hn",
                "posteo.hr",
                "posteo.hu",
                "posteo.ie",
                "posteo.in",
                "posteo.is",
                "posteo.it",
                "posteo.jp",
                "posteo.la",
                "posteo.li",
                "posteo.lt",
                "posteo.lu",
                "posteo.me",
                "posteo.mx",
                "posteo.my",
                "posteo.net",
                "posteo.nl",
                "posteo.no",
                "posteo.nz",
                "posteo.org",
                "posteo.pe",
                "posteo.pl",
                "posteo.pm",
                "posteo.pt",
                "posteo.ro",
                "posteo.ru",
                "posteo.se",
                "posteo.sg",
                "posteo.si",
                "posteo.tn",
                "posteo.uk",
                "posteo.us"]

            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.109 Safari/537.36',
                'Referer': 'https://posteo.de/en/signup',
                'X-Requested-With': 'XMLHttpRequest'}

            sreq = req_session_fun()
            try:
                posteoURL = "https://posteo.de/users/new/check_username?user%5Busername%5D={}".format(target)
                chkPosteo = await sreq.get(posteoURL, headers=headers, timeout=5)

                async with chkPosteo:
                    if chkPosteo.status == 200:
                        resp = await chkPosteo.text()
                        if resp == "false":
                            result["Posteo"] = ["{}@posteo.net".format(target),
                                                "~50 aliases: https://posteo.de/en/help/which-domains-are-available-to-use-as-a-posteo-alias-address"]
            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def mailbox(target, req_session_fun) -> Dict:  # tor RU
            result = {}

            mailboxURL = "https://register.mailbox.org:443/ajax"
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.109 Safari/537.36"}
            mailboxJSON = {"account_name": target, "action": "validateAccountName"}

            existiert = "Der Accountname existiert bereits."
            sreq = req_session_fun()

            try:
                chkMailbox = await sreq.post(mailboxURL, headers=headers, json=mailboxJSON, timeout=10)

                async with chkMailbox:
                    resp = await chkMailbox.text()
                    if resp == existiert:
                        result["MailBox"] = "{}@mailbox.org".format(target)
            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def firemail(target, req_session_fun) -> Dict:  # tor RU
            result = {}

            firemailSucc = []

            firemailDomains = ["firemail.at", "firemail.de", "firemail.eu"]

            headers = {'User-Agent': random.choice(uaLst),
                       'Referer': 'https://firemail.de/E-Mail-Adresse-anmelden',
                       'X-Requested-With': 'XMLHttpRequest'}
            sreq = req_session_fun()

            for firemailDomain in firemailDomains:
                try:
                    targetMail = "{}@{}".format(target, firemailDomain)

                    firemailURL = "https://firemail.de/index.php?action=checkAddressAvailability&address={}".format(
                        targetMail)
                    chkFiremail = await sreq.get(firemailURL, headers=headers, timeout=10)

                    async with chkFiremail:
                        if chkFiremail.status == 200:
                            resp = await chkFiremail.text()
                            if '>0<' in resp:
                                firemailSucc.append("{}".format(targetMail))
                except Exception as e:
                    logger.error(e, exc_info=True)

                sleep(random.uniform(2, 4))

            if firemailSucc:
                result["Firemail"] = firemailSucc

            await sreq.close()

            return result

        async def fastmail(target, req_session_fun) -> Dict:  # sanctions against Russia) TOR + 4 min for check in loop(
            result = {}

            # Registration form on fastmail website automatically lowercase all input.
            # If uppercase letters are used false positive results are returned.
            target = target.lower()

            # validate target syntax to prevent false positive results
            match = re.search(r'^\w{3,40}$', target)

            if not match:
                return result

            fastmailSucc = []

            fastmailLst = [
                "fastmail.com", "fastmail.cn", "fastmail.co.uk", "fastmail.com.au",
                "fastmail.de", "fastmail.es", "fastmail.fm", "fastmail.fr",
                "fastmail.im", "fastmail.in", "fastmail.jp", "fastmail.mx",
                "fastmail.net", "fastmail.nl", "fastmail.org", "fastmail.se",
                "fastmail.to", "fastmail.tw", "fastmail.uk", "fastmail.us",
                "123mail.org", "airpost.net", "eml.cc", "fmail.co.uk",
                "fmgirl.com", "fmguy.com", "mailbolt.com", "mailcan.com",
                "mailhaven.com", "mailmight.com", "ml1.net", "mm.st",
                "myfastmail.com", "proinbox.com", "promessage.com", "rushpost.com",
                "sent.as", "sent.at", "sent.com", "speedymail.org",
                "warpmail.net", "xsmail.com", "150mail.com", "150ml.com",
                "16mail.com", "2-mail.com", "4email.net", "50mail.com",
                "allmail.net", "bestmail.us", "cluemail.com", "elitemail.org",
                "emailcorner.net", "emailengine.net", "emailengine.org", "emailgroups.net",
                "emailplus.org", "emailuser.net", "f-m.fm", "fast-email.com",
                "fast-mail.org", "fastem.com", "fastemail.us", "fastemailer.com",
                "fastest.cc", "fastimap.com", "fastmailbox.net", "fastmessaging.com",
                "fea.st", "fmailbox.com", "ftml.net", "h-mail.us",
                "hailmail.net", "imap-mail.com", "imap.cc", "imapmail.org",
                "inoutbox.com", "internet-e-mail.com", "internet-mail.org",
                "internetemails.net", "internetmailing.net", "jetemail.net",
                "justemail.net", "letterboxes.org", "mail-central.com", "mail-page.com",
                "mailandftp.com", "mailas.com", "mailc.net", "mailforce.net",
                "mailftp.com", "mailingaddress.org", "mailite.com", "mailnew.com",
                "mailsent.net", "mailservice.ms", "mailup.net", "mailworks.org",
                "mymacmail.com", "nospammail.net", "ownmail.net", "petml.com",
                "postinbox.com", "postpro.net", "realemail.net", "reallyfast.biz",
                "reallyfast.info", "speedpost.net", "ssl-mail.com", "swift-mail.com",
                "the-fastest.net", "the-quickest.com", "theinternetemail.com",
                "veryfast.biz", "veryspeedy.net", "yepmail.net", "your-mail.com"]

            headers = {"User-Agent": random.choice(uaLst),
                       "Referer": "https://www.fastmail.com/signup/",
                       "Content-type": "application/json",
                       "X-TrustedClient": "Yes",
                       "Origin": "https://www.fastmail.com"}

            fastmailURL = "https://www.fastmail.com:443/jmap/setup/"
            sreq = req_session_fun()

            for fmdomain in fastmailLst:
                # print(fastmailLst.index(fmdomain)+1, fmdomain)

                fmmail = "{}@{}".format(target, fmdomain)

                fastmailJSON = {"methodCalls": [["Signup/getEmailAvailability", {"email": fmmail}, "0"]],
                                "using": ["https://www.fastmail.com/dev/signup"]}

                try:
                    chkFastmail = await sreq.post(fastmailURL, headers=headers, json=fastmailJSON, timeout=5)

                    async with chkFastmail:
                        if chkFastmail.status == 200:
                            resp = await chkFastmail.json()
                            fmJson = resp['methodResponses'][0][1]['isAvailable']
                            if fmJson is False:
                                fastmailSucc.append("{}".format(fmmail))

                except Exception as e:
                    logger.error(e, exc_info=True)

                sleep(random.uniform(0.5, 1.1))

            if fastmailSucc:
                result["Fastmail"] = fastmailSucc

            await sreq.close()

            return result

        async def startmail(target, req_session_fun) -> Dict:  # TOR
            result = {}

            startmailURL = "https://mail.startmail.com:443/api/AvailableAddresses/{}%40startmail.com".format(target)
            headers = {"User-Agent": random.choice(uaLst),
                       "X-Requested-With": "1.94.0"}
            sreq = req_session_fun()

            try:
                chkStartmail = await sreq.get(startmailURL, headers=headers, timeout=10)

                async with chkStartmail:
                    if chkStartmail.status == 404:
                        result["StartMail"] = "{}@startmail.com".format(target)

            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def kolab(target, req_session_fun) -> Dict:
            result: Dict[str, List] = {}

            kolabLst = ["mykolab.com",
                        "attorneymail.ch",
                        "barmail.ch",
                        "collaborative.li",
                        "diplomail.ch",
                        "freedommail.ch",
                        "groupoffice.ch",
                        "journalistmail.ch",
                        "legalprivilege.ch",
                        "libertymail.co",
                        "libertymail.net",
                        "mailatlaw.ch",
                        "medicmail.ch",
                        "medmail.ch",
                        "mykolab.ch",
                        "myswissmail.ch",
                        "opengroupware.ch",
                        "pressmail.ch",
                        "swisscollab.ch",
                        "swissgroupware.ch",
                        "switzerlandmail.ch",
                        "trusted-legal-mail.ch",
                        "kolabnow.com",
                        "kolabnow.ch"]

            ''' # old cool version ;(
            kolabURL = "https://kolabnow.com:443/cockpit/json.php"
            headers = { "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:60.0) Gecko/20100101 Firefox/60.0",
                        "Referer": "https://kolabnow.com/cockpit/signup/individual",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest"}

            try:
                kolabStatus = sreq.post(kolabURL, headers=headers)
                print(kolabStatus.status_code)

                if kolabStatus.status_code == 200:

                    for kolabdomain in kolabLst:

                        kolabPOST = {"validate": "username",
                                    "accounttype": "individual",
                                    "username": target,
                                    "domain": kolabdomain,
                                    "_action_": "/signup/validate"}

                        try:

                            chkKolab = sreq.post(kolabURL, headers=headers, data=kolabPOST)

                            if chkKolab.status_code == 200:

                                kolabJSON = chkKolab.json()

                                if kolabJSON['errors']:
                                    suc = "This email address is not available"
                                    if kolabJSON['errors']['username'] == suc:
                                        print("[+] Success with {}@{}".format(target, kolabdomain))

                        except Exception as e:
                            pass

                        sleep(random.uniform(1, 3))

            except Exception as e:
                #pass
                print e
            '''

            kolabURL = "https://kolabnow.com/api/auth/signup"
            headers = {"User-Agent": random.choice(uaLst),
                       "Referer": "https://kolabnow.com/signup/individual",
                       "Content-Type": "application/json;charset=utf-8",
                       "X-Test-Payment-Provider": "mollie",
                       "X-Requested-With": "XMLHttpRequest"}
            sreq = req_session_fun()

            kolabStatus = await sreq.post(kolabURL, headers={"User-Agent": random.choice(uaLst)}, timeout=10)

            if kolabStatus.status == 422:

                kolabpass = randstr(12)
                kolabsuc = "The specified login is not available."

                for kolabdomain in kolabLst:

                    kolabPOST = {"login": target,
                                 "domain": kolabdomain,
                                 "password": kolabpass,
                                 "password_confirmation": kolabpass,
                                 "voucher": "",
                                 "code": "bJDmpWw8sO85KlgSETPWtnViDgQ1S0MO",
                                 "short_code": "VHBZX"}

                    try:
                        # chkKolab = sreq.post(kolabURL, headers=headers, data=kolabPOST)
                        chkKolab = await sreq.post(kolabURL, headers=headers, data=json.dumps(kolabPOST), timeout=10)
                        resp = await chkKolab.text()

                        if chkKolab.status == 200:

                            kolabJSON = chkKolab.json()
                            if kolabJSON["errors"]["login"] == kolabsuc:
                                # print("[+] Success with {}@{}".format(target, kolabdomain))
                                pass
                            else:
                                if kolabJSON["errors"]:
                                    pass
                                    # print(kolabJSON["errors"])

                    except Exception as e:
                        logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def bigmir(target, req_session_fun) -> Dict:
            result = {}

            bigmirSucc = []
            bigmirMail = ["i.ua", "ua.fm", "email.ua"]
            sreq = req_session_fun()

            for maildomain in bigmirMail:
                try:
                    bigmirChkJS = "https://passport.i.ua/js/free.js?15908746259240-xml"

                    headers = {
                        'Pragma': 'no-cache',
                        'Origin': 'https://passport.i.ua',
                        'User-Agent': random.choice(uaLst),
                        'Content-Type': 'application/octet-stream',
                        'Referer': 'https://passport.i.ua/registration/'
                    }

                    bm_data = "login={}@{}".format(target, maildomain)

                    bigmirChk = await sreq.post(bigmirChkJS, headers=headers, data=bm_data, timeout=10)

                    async with bigmirChk:
                        if bigmirChk.status == 200:
                            exist = "'free': false"

                            resp = await bigmirChk.text()
                            if "'free': false" in resp:
                                bigmirSucc.append("{}@{}".format(target, maildomain))

                    sleep(random.uniform(2, 4))

                except Exception as e:
                    logger.error(e, exc_info=True)

            if bigmirSucc:
                result["Bigmir"] = bigmirSucc

            await sreq.close()

            return result

        async def tutby(target, req_session_fun) -> Dict:  # Down
            result = {}

            smtp_check, error = await code250('tut.by', target)
            if smtp_check:
                result['Tut.by'] = smtp_check[0]
                return result

            sreq = req_session_fun()

            try:
                target64 = str(base64.b64encode(target.encode()))
                tutbyChkURL = "https://profile.tut.by/requests/index.php"

                headers = {
                    'Pragma': 'no-cache',
                    'Origin': 'https://profile.tut.by',
                    'User-Agent': random.choice(uaLst),
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'Referer': 'https://profile.tut.by/register.html',
                    'X-Requested-With': 'XMLHttpRequest'
                }

                tutbyData = f"action=lgval&l={target64}"
                tutbyChk = await sreq.post(tutbyChkURL, headers=headers, data=tutbyData, timeout=10)

                if tutbyChk.status == 200:
                    exist = '[{"success":true}]'
                    resp = await tutbyChk.text()

                    if exist == resp:
                        result['Tut.by'] = '{}@tut.by'.format(target)

            except Exception as e:
                logger.error(e, exc_info=True)
                error = str(e)

            await sreq.close()

            return result, error

        async def xmail(target, req_session_fun) -> Dict:
            result = {}

            sreq = req_session_fun()
            xmailURL = "https://xmail.net:443/app/signup/checkusername"
            headers = {"User-Agent": random.choice(uaLst),
                       "Accept": "application/json, text/javascript, */*",
                       "Referer": "https://xmail.net/app/signup",
                       "Content-Type": "application/x-www-form-urlencoded",
                       "X-Requested-With": "XMLHttpRequest",
                       "Connection": "close"}

            xmailPOST = {"username": target, "firstname": '', "lastname": ''}

            try:
                xmailChk = await sreq.post(xmailURL, headers=headers, data=xmailPOST, timeout=10)

                async with xmailChk:
                    resp = await xmailChk.json()
                    if not resp['username']:
                        result["Xmail"] = "{}@xmail.net".format(target)

            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def ukrnet(target, req_session_fun) -> Dict:
            result = {}

            ukrnet_reg_urk = "https://accounts.ukr.net:443/registration"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "DNT": "1",
                "Connection": "close",
                "Upgrade-Insecure-Requests": "1"}

            sreq = req_session_fun()

            try:

                get_reg_ukrnet = await sreq.get(ukrnet_reg_urk, headers=headers, timeout=10)

                async with get_reg_ukrnet:
                    if get_reg_ukrnet.status == 200:
                        ukrnet_cookies = sreq.cookie_jar
                        if ukrnet_cookies:
                            ukrnetURL = "https://accounts.ukr.net:443/api/v1/registration/reserve_login"
                            ukrnetPOST = {"login": target}

                            ukrnetChk = await sreq.post(ukrnetURL, headers=headers, json=ukrnetPOST, timeout=10)

                            async with ukrnetChk:
                                if ukrnetChk.status == 200:
                                    resp = await ukrnetChk.json()
                                    if not resp['available']:
                                        result["UkrNet"] = "{}@ukr.net".format(target)
            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def runbox(target, req_session_fun) -> Dict:
            result = {}

            runboxSucc = []
            runboxLst = ["mailhost.work",
                         "mailhouse.biz",
                         "messagebox.email",
                         "offshore.rocks",
                         "rbox.co",
                         "rbox.me",
                         "rbx.email",
                         "rbx.life",
                         "rbx.run",
                         "rnbx.uk",
                         "runbox.at",
                         "runbox.biz",
                         "runbox.bz",
                         "runbox.ch",
                         "runbox.co",
                         "runbox.co.in",
                         "runbox.com",
                         "runbox.dk",
                         "runbox.email",
                         "runbox.eu",
                         "runbox.is",
                         "runbox.it",
                         "runbox.ky",
                         "runbox.li",
                         "runbox.me",
                         "runbox.nl",
                         "runbox.no",
                         "runbox.uk",
                         "runbox.us",
                         "xobnur.uk"]

            headers = {"User-Agent": random.choice(uaLst),
                       "Origin": "https://runbox.com",
                       "Referer": "https://runbox.com/signup?runbox7=1"}

            sreq = req_session_fun()
            for rboxdomain in runboxLst:
                try:
                    data = {"type": "person", "company": "", "first_name": "", "last_name": "", "user": target,
                            "userdomain": "domainyouown.com", "runboxDomain": rboxdomain, "password": "",
                            "password_strength": "", "email_alternative": "", "phone_number_cellular": "",
                            "referrer": "", "phone_number_home": "", "g-recaptcha-response": "",
                            "h-captcha-response": "", "signup": "%A0Set+up+my+Runbox+account%A0",
                            "av": "y", "as": "y", "domain": "", "accountType": "person", "domainType": "runbox",
                            "account_number": "", "timezone": "undefined", "runbox7": "1"}

                    chkRunbox = await sreq.post('https://runbox.com/signup/signup', headers=headers, data=data,
                                                timeout=5)

                    if chkRunbox.status == 200:
                        resp = await chkRunbox.text()
                        if "The specified username is already taken" in resp:
                            runboxSucc.append("{}@{}".format(target, rboxdomain))

                except Exception as e:
                    logger.error(e, exc_info=True)

                finally:
                    sleep(random.uniform(1, 2.1))

            if runboxSucc:
                result["Runbox"] = runboxSucc

            await sreq.close()

            return result

        async def iCloud(target, req_session_fun) -> Dict:
            result: Dict[str, List] = {}

            domains = [
                'icloud.com',
                'me.com',
                'mac.com',
            ]

            sreq = req_session_fun()

            for domain in domains:
                try:
                    email = f'{target}@{domain}'
                    headers = {
                        'User-Agent': random.choice(uaLst),
                        'sstt': 'zYEaY3WeI76oAG%2BCNPhCiGcKUCU0SIQ1cIO2EMepSo8egjarh4MvVPqxGOO20TYqlbJI%2Fqs57WwAoJarOPukJGJvgOF7I7C%2B1jAE5vZo%2FSmYkvi2e%2Bfxj1od1xJOf3lnUXZlrnL0QWpLfaOgOwjvorSMJ1iuUphB8bDqjRzyb76jzDU4hrm6TzkvxJdlPCCY3JVTfAZFgXRoW9VlD%2Bv3VF3in1RSf6Er2sOS12%2FZJR%2Buo9ubA2KH9RLRzPlr1ABtsRgw6r4zbFbORaKTSVWGDQPdYCaMsM4ebevyKj3aIxXa%2FOpS6SHcx1KrvtOAUVhR9nsfZsaYfZvDa6gzpcNBF9domZJ1p8MmThEfJra6LEuc9ssZ3aWn9uKqvT3pZIVIbgdZARL%2B6SK1YCN7',
                        'Content-Type': 'application/json',
                    }

                    data = {'id': email}
                    check = await sreq.post('https://iforgot.apple.com/password/verify/appleid', headers=headers,
                                            data=json.dumps(data), allow_redirects=False, timeout=10)
                    if check.headers and check.headers.get('Location', '').startswith('/password/authenticationmethod'):
                        if not result:
                            result = {'iCloud': []}
                        result['iCloud'].append(email)
                except Exception as e:
                    logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def duckgo(target, req_session_fun) -> Dict:
            result = {}

            duckURL = "https://quack.duckduckgo.com/api/auth/signup"

            headers = {"User-Agent": random.choice(uaLst), "Origin": "https://duckduckgo.com",
                       "Sec-Fetch-Dest": "empty",
                       "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-site", "Te": "trailers",
                       "Referer": "https://duckduckgo.com/"}

            data = {
                "code": (None, "01337"),
                "user": (None, target),
                "email": (None, "mail@example.com")

            }

            sreq = req_session_fun()

            try:
                checkDuck = await sreq.post(duckURL, headers=headers, data=data, timeout=5)

                resp = await checkDuck.text()
                # if checkDuck.json()['error'] == "unavailable_username":
                if "unavailable_username" in resp:
                    result["DuckGo"] = "{}@duck.com".format(target)

            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def ctemplar(target, req_session_fun) -> Dict:

            result = {}

            # validate target syntax to prevent false positive results (e.g. no dot at the end of target allowed)
            match = re.search(r'^[a-zA-Z][\w\-.]{2,}[a-zA-Z\d]$', target)

            if not match:
                return result

            sreq = req_session_fun()

            ctURL = "https://api.ctemplar.com/auth/check-username/"
            ctJSON = {"username": target}

            headers = {"User-Agent": random.choice(uaLst),
                       "Accept": "application/json, text/plain, */*",
                       "Referer": "https://mail.ctemplar.com/",
                       "Content-Type": "application/json",
                       "Origin": "https://mail.ctemplar.com"}

            try:
                chkCT = await sreq.post(ctURL, headers=headers, json=ctJSON)

                if chkCT.status == 200:
                    resp = await chkCT.json()
                    ct_exists = resp['exists']
                    if ct_exists:
                        result["CTemplar"] = "{}@ctemplar.com".format(target)

            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def hushmail(target, req_session_fun) -> Dict:

            result = {}

            hushDomains = ["hushmail.com", "hush.com", "therapyemail.com", "counselingmail.com", "therapysecure.com",
                           "counselingsecure.com"]
            hushSucc = []
            sreq = req_session_fun()

            hush_ts = int(datetime.datetime.now().timestamp())

            hushURL = "https://secure.hushmail.com/signup/create?format=json"
            ref_header = "https://secure.hushmail.com/signup/?package=hushmail-for-healthcare-individual-5-form-monthly&source=website&tag=page_business_healthcare,btn_healthcare_popup_signup_individual&coupon_code="
            hush_UA = random.choice(uaLst)

            hushpass = randstr(15)

            for hushdomain in hushDomains:

                # hushpass = randstr(15)
                hush_ts = int(datetime.datetime.now().timestamp())

                headers = {"User-Agent": hush_UA,
                           "Accept": "application/json, text/javascript, */*; q=0.01",
                           "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                           "X-Hush-Ajax-Start-Time": str(hush_ts), "X-Requested-With": "XMLHttpRequest",
                           "Origin": "https://secure.hushmail.com", "Referer": ref_header,
                           "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"}

                data = {"hush_customerid": '', "hush_exitmethod": "GET",
                        "skin": "bootstrap311", "hush_cc_country": '',
                        "trial_mode": '', "parent": '', "parent_code": '',
                        "coupon_code": '', "form_token": "6e1555a603f6e762a090e6f6b885122f_dabaddeadbee",
                        "__hushform_extra_fields": '', "hush_username": target, "hush_domain": hushdomain,
                        "hush_pass1": hushpass, "hush_pass2": hushpass,
                        "hush_exitpage": "https://secure.hushmail.com/pay?package=hushmail-for-healthcare-individual-5-form-monthly",
                        "package": "hushmail-for-healthcare-individual-5-form-monthly",
                        "hush_reservation_code": '', "hush_customerid": '', "hush_tos": '', "hush_privacy_policy": '',
                        "hush_additional_tos": '', "hush_email_opt_in": '', "isValidAjax": "newaccountform"}

                try:
                    hushCheck = await sreq.post(hushURL, headers=headers, data=data, timeout=5)

                    if hushCheck.status == 200:
                        resp = await hushCheck.json()
                        if "'{}' is not available".format(target) in resp['formValidation']['hush_username']:
                            hushMail = "{}@{}".format(target, hushdomain)
                            hushSucc.append(hushMail)

                except Exception as e:
                    logger.error(e, exc_info=True)

                sleeper(hushDomains, 1.1, 2.2)

            if hushSucc:
                result["HushMail"] = hushSucc

            await sreq.close()

            return result

        async def emailn(target, req_session_fun) -> Dict:
            result = {}

            emailnURL = "https://www.emailn.de/webmail/index.php?action=checkAddressAvailability&address={}@emailn.de".format(
                target)
            headers = {'User-Agent': random.choice(uaLst)}
            sreq = req_session_fun()

            try:
                emailnChk = await sreq.get(emailnURL, headers=headers, timeout=10)

                async with emailnChk:
                    if emailnChk.status == 200:
                        resp = await emailnChk.text()
                        if ">0<" in resp:
                            result["emailn"] = "{}@emailn.de".format(target)
            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def aikq(target, req_session_fun) -> Dict:
            result = {}
            aikqSucc = []

            aikqLst = ["aikq.com",
                       "aikq.co",
                       "aikq.eu",
                       "aikq.de",
                       "mails.eu",
                       "aikq.net",
                       "aikq.org",
                       "aikq.biz",
                       "aikq.tv",
                       "aikq.at",
                       "aikq.uk",
                       "aikq.co.uk",
                       "aikq.fr",
                       "aikq.be",
                       "aikq.pl",
                       "aikq.email",
                       "aikq.info",
                       "mailbox.info",
                       "mails.info",
                       "aikq.cloud",
                       "aikq.chat",
                       "aikq.name",
                       "aikq.wiki",
                       "aikq.ae",
                       "aikq.asia",
                       "aikq.by",
                       "aikq.com.br",
                       "aikq.cz",
                       "aikq.ie",
                       "aikq.in",
                       "aikq.jp",
                       "aikq.li",
                       "aikq.me",
                       "aikq.mx",
                       "aikq.nl",
                       "aikq.nz",
                       "aikq.qa",
                       "aikq.sk",
                       "aikq.tw",
                       "aikq.us",
                       "aikq.ws"]

            headers = {'User-Agent': random.choice(uaLst)}
            sreq = req_session_fun()

            for maildomain in aikqLst:
                try:
                    targetMail = "{}@{}".format(target, maildomain)
                    aikqUrl = "https://www.aikq.de/index.php?action=checkAddressAvailability&address={}".format(
                        targetMail)
                    chkAikq = await sreq.get(aikqUrl, headers=headers, timeout=5)

                    async with chkAikq:
                        if chkAikq.status == 200:
                            resp = await chkAikq.text()
                            if '>0<' in resp:
                                aikqSucc.append(targetMail)
                except Exception as e:
                    logger.error(e, exc_info=True)

                sleep(random.uniform(2, 4))

            if aikqSucc:
                result["Aikq"] = aikqSucc

            await sreq.close()

            return result

        async def vivaldi(target, req_session_fun) -> Dict:
            result = {}

            vivaldiURL = "https://login.vivaldi.net:443/profile/validateField"
            headers = {
                "User-Agent": random.choice(uaLst),
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://login.vivaldi.net",
                "Referer": "https://login.vivaldi.net/profile/id/signup"
            }

            vivaldiPOST = {"field": "username", "value": target}

            sreq = req_session_fun()

            try:
                vivaldiChk = await sreq.post(vivaldiURL, headers=headers, data=vivaldiPOST, timeout=5)

                body = await vivaldiChk.json(content_type=None)

                if 'error' in body and body['error'] == "User exists [1007]":
                    result["Vivaldi"] = "{}@vivaldi.net".format(target)

            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def mailDe(target, req_session_fun) -> Dict:
            result = {}
            mailChkLst, error = await code250("mail.de", target)
            if mailChkLst:
                result["mail.de"] = mailChkLst[0]
            await asyncio.sleep(0)
            return result, error

        async def wp(target, req_session_fun) -> Dict:
            result = {}

            wpURL = "https://poczta.wp.pl/api/v1/public/registration/accounts/availability"
            headers = {
                "User-Agent": random.choice(uaLst),
                "Content-Type": "application/json;charset=UTF-8",
                "Origin": "https://poczta.wp.pl",
                "Referer": "https://poczta.wp.pl/rejestracja/",
                "Accept": "application/json"
            }

            data = f'{{"login":"{target}"}}'

            sreq = req_session_fun()

            try:
                wpChk = await sreq.put(wpURL, headers=headers, data=data, timeout=5)

                body = await wpChk.json(content_type=None)

                if "Podany login jest niedostępny." in str(body):
                    result["Wirtualna Polska"] = f"{target}@wp.pl"

            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def gazeta(target, req_session_fun) -> Dict:
            result = {}

            gazetaURL = f"https://konto.gazeta.pl/konto/checkLogin?login={target}&nosuggestions=true"
            headers = {
                "User-Agent": random.choice(uaLst),
                "Referer": "https://konto.gazeta.pl/konto/rejestracja.do",
                "Accept": "*/*"
            }

            sreq = req_session_fun()

            try:
                gazetaChk = await sreq.get(gazetaURL, headers=headers, timeout=5)

                body = await gazetaChk.json(content_type=None)

                if body["available"] == "0":
                    result["Gazeta.pl"] = f"{target}@gazeta.pl"

            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def intpl(target, req_session_fun) -> Dict:
            result = {}

            intURL = f"https://int.pl/v1/user/checkEmail"
            headers = {
                "User-Agent": random.choice(uaLst),
                "Origin": "https://int.pl",
                "Referer": "https://int.pl/",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
            }

            data = f"login={target}&subdomain=&domain=int.pl"

            sreq = req_session_fun()

            try:
                intChk = await sreq.post(intURL, headers=headers, data=data, timeout=5)

                body = await intChk.json(content_type=None)

                if body["result"]["data"]["login"] == 0:
                    result["int.pl"] = f"{target}@int.pl"

            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def o2(target, req_session_fun) -> Dict:
            result = {}

            o2URL = "https://poczta.o2.pl/api/v1/public/registration/accounts/availability"
            headers = {
                "User-Agent": random.choice(uaLst),
                "Content-Type": "application/json;charset=UTF-8",
                "Origin": "https://poczta.o2.pl",
                "Referer": "https://poczta.o2.pl/rejestracja/",
                "Accept": "application/json"
            }

            data = f'{{"login":"{target}","sex":""}}'

            sreq = req_session_fun()

            try:
                wpChk = await sreq.put(o2URL, headers=headers, data=data, timeout=5)

                body = await wpChk.json(content_type=None)

                if "Podany login jest niedostępny." in str(body):
                    result["O2"] = f"{target}@o2.pl"

            except Exception as e:
                logger.error(e, exc_info=True)

            await sreq.close()

            return result

        async def interia(target, req_session_fun) -> Dict:
            result = {}
            interiaSucc = []

            interiaLst = ["interia.pl",
                          "interia.eu",
                          "intmail.pl",
                          "adresik.net",
                          "vip.interia.pl",
                          "ogarnij.se",
                          "poczta.fm",
                          "interia.com",
                          "interiowy.pl",
                          "pisz.to",
                          "pacz.to"]

            headers = {
                'User-Agent': random.choice(uaLst),
                'Content-Type': 'application/json',
                'Accept': 'application/json; q=1.0, text/*; q=0.8, */*; q=0.1',
                'Origin': 'https://konto-pocztowe.interia.pl',
                'Referer': 'https://konto-pocztowe.interia.pl/'
            }

            sreq = req_session_fun()

            for maildomain in interiaLst:
                try:
                    targetMail = f"{target}@{maildomain}"
                    data = f'{{"email":"{targetMail}"}}'

                    interiaUrl = "https://konto-pocztowe.interia.pl/odzyskiwanie-dostepu/sms"
                    chkInteria = await sreq.post(interiaUrl, headers=headers, data=data, timeout=5)

                    async with chkInteria:
                        if chkInteria.status == 404:
                            resp = await chkInteria.json(content_type=None)
                            if resp["data"]["message"] == "Użytkownik nie istnieje w systemie":
                                interiaSucc.append(targetMail)
                except Exception as e:
                    logger.error(e, exc_info=True)

                sleep(random.uniform(2, 4))

            if interiaSucc:
                result["Interia"] = interiaSucc

            await sreq.close()

            return result

        ####################################################################################

        async def print_results(checker, stringToCheck: str, req_session_function, entityUID):
            originalString = stringToCheck
            if stringToCheck.startswith('@'):
                stringToCheck = stringToCheck[1:]
            if '@' in stringToCheck:
                stringToCheck = stringToCheck.split('@', 1)[0]  # The first part of an email address won't have a '@'.

            err = None
            res = await checker(stringToCheck, req_session_function)

            if isinstance(res, tuple):
                res, err = res

            if not res or err:
                return

            for provider, emails in res.items():
                if isinstance(emails, str):
                    emails = [emails]
                for email in emails:
                    if email != originalString:
                        return_results.append([{'Email Address': email,
                                                'Entity Type': 'Email Address'},
                                               {entityUID: {'Resolution': 'MailCat Existing Email Identified',
                                                            'Notes': ''}}])

        CHECKERS = [gmail, yandex, proton, mailRu,
                    rambler, tuta, yahoo, outlook,
                    zoho, eclipso, posteo, mailbox,
                    firemail, fastmail, startmail,
                    bigmir, tutby, xmail, ukrnet,
                    runbox, iCloud, duckgo, hushmail,
                    ctemplar, aikq, emailn, vivaldi,
                    mailDe, wp, gazeta, intpl,
                    o2, interia]  # -kolab -lycos(false((( )

        if parameters['Route traffic over Proxy'] != 'NONE':
            req_session_fun = via_proxy(parameters['Route traffic over Proxy'])
        elif parameters['Route traffic over Tor'] == 'Yes':
            req_session_fun = via_tor
        else:
            req_session_fun = simple_session

        async def parseEntities():
            for entity in entityJsonList:
                uid = entity['uid']
                entityType = entity['Entity Type']
                if entityType == 'Phrase':
                    target = entity['Phrase']
                elif entityType == 'Email Address':
                    target = entity['Email Address']
                else:
                    target = entity['User Name']

                await asyncio.gather(*[print_results(checker, target, req_session_fun, uid) for checker in CHECKERS])

        def processFunc(process_queue: Queue):
            import asyncio
            from concurrent.futures import ThreadPoolExecutor

            executor = ThreadPoolExecutor(15)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.set_default_executor(executor)
            loop.run_until_complete(parseEntities())
            loop.close()
            process_queue.put(return_results)

        p = Process(target=processFunc, args=(return_results_queue,))
        p.start()
        p.join()
        try:
            return_results = return_results_queue.get(timeout=1)
            return return_results
        except Empty:
            return "Error occurred when processing entities for Mailcat module."
