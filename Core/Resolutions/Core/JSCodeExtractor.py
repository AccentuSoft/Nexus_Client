#!/usr/bin/env python3


class JSCodeExtractor:
    # A string that is treated as the name of this resolution.
    name = "Extract Tracking Codes"

    # A string that describes this resolution.
    description = "Returns Nodes of 'ca-pub', 'ua' and 'gtm' tracking codes for websites and/or domains."

    originTypes = {'Website', 'Domain'}

    resultTypes = {'Phrase'}

    parameters = {}

    def resolution(self, entityJsonList, parameters):
        from playwright.sync_api import sync_playwright
        import re
        returnResults = []
        requestUrlsParsed = set()

        uaRegex = re.compile(r'\bUA-\d{4,10}-\d{1,4}\b', re.IGNORECASE)
        pubRegex = re.compile(r'\bca-pub-\d{1,16}\b', re.IGNORECASE)
        gtmRegex = re.compile(r'\bGTM-[A-Z0-9]{1,7}\b', re.IGNORECASE)
        gRegex = re.compile(r'\bG-[A-Z0-9]{1,15}\b', re.IGNORECASE)
        qualtricsRegex = re.compile(r'\bQ_ZID=[a-zA-Z_0-9]*\b', re.IGNORECASE)

        def GetTrackingCodes(pageUid, requestUrl) -> None:
            if requestUrl not in requestUrlsParsed:
                requestUrlsParsed.add(requestUrl)
                for uaCode in uaRegex.findall(requestUrl):
                    returnResults.append([{'Phrase': uaCode,
                                           'Entity Type': 'Phrase'},
                                          {pageUid: {'Resolution': 'Google UA Tracking Code',
                                                     'Notes': ''}}])
                for pubCode in pubRegex.findall(requestUrl):
                    returnResults.append([{'Phrase': pubCode,
                                           'Entity Type': 'Phrase'},
                                          {pageUid: {'Resolution': 'Google AdSense ca-pub Tracking Code',
                                                     'Notes': ''}}])
                for gtmCode in gtmRegex.findall(requestUrl):
                    returnResults.append([{'Phrase': gtmCode,
                                           'Entity Type': 'Phrase'},
                                          {pageUid: {'Resolution': 'Google GTM Tracking Code',
                                                     'Notes': ''}}])
                for gCode in gRegex.findall(requestUrl):
                    returnResults.append([{'Phrase': gCode,
                                           'Entity Type': 'Phrase'},
                                          {pageUid: {'Resolution': 'Google G Tracking Code',
                                                     'Notes': ''}}])
                for qCode in qualtricsRegex.findall(requestUrl):
                    returnResults.append([{'Phrase': qCode[6:],
                                           'Entity Type': 'Phrase'},
                                          {pageUid: {'Resolution': 'Qualtrics Tracking Code',
                                                     'Notes': ''}}])

        with sync_playwright() as p:
            browser = p.firefox.launch()
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:94.0) Gecko/20100101 Firefox/94.0'
            )
            page = context.new_page()
            for site in entityJsonList:
                uid = site['uid']
                url = site.get('URL') if site.get('Entity Type', '') == 'Website' else site.get('Domain Name', None)
                if url is None:
                    continue
                if not url.startswith('http://') and not url.startswith('https://'):
                    url = 'http://' + url

                # Subscribe to "request" events.
                page.on("request", lambda request: GetTrackingCodes(uid, request.url))
                page.goto(url)
            page.close()
            browser.close()

        return returnResults
