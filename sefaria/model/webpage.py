# coding=utf-8
from urllib.parse import urlparse
import regex as re
from datetime import datetime
from collections import defaultdict

from . import abstract as abst
from . import text
from sefaria.system.database import db

from sefaria.system.cache import in_memory_cache

import structlog
logger = structlog.get_logger(__name__)
from collections import Counter
from sefaria.utils.calendars import daf_yomi, parashat_hashavua_and_haftara
from datetime import datetime, timedelta
from sefaria.system.exceptions import InputError

class WebPage(abst.AbstractMongoRecord):
    collection = 'webpages'

    required_attrs = [
        "url",
        "title",
        "refs",
        "lastUpdated",
    ]
    optional_attrs = [
        "description",
        "expandedRefs",
        "body",
        "linkerHits"
    ]

    def load(self, url_or_query):
        query = {"url": WebPage.normalize_url(url_or_query)} if isinstance(url_or_query, str) else url_or_query
        return super(WebPage, self).load(query)

    def _set_derived_attributes(self):
        if getattr(self, "url", None):
            self.domain      = WebPage.domain_for_url(self.url)
            self.favicon     = "https://www.google.com/s2/favicons?domain={}".format(self.domain)
            self._site_data  = WebPage.site_data_for_domain(self.domain)
            self.site_name   = self._site_data["name"] if self._site_data else self.domain
            self.whitelisted = self._site_data["is_whitelisted"] if self._site_data else False

    def _init_defaults(self):
        self.linkerHits = 0

    def _normalize(self):
        super(WebPage, self)._normalize()
        self.url = WebPage.normalize_url(self.url)
        self.refs = [text.Ref(ref).normal() for ref in self.refs if text.Ref.is_ref(ref)]
        self.refs = list(set(self.refs))
        self.expandedRefs = text.Ref.expand_refs(self.refs)

    def _validate(self):
        super(WebPage, self)._validate()


    def get_website(self, dict_only=False):
        # returns the corresponding WebSite.  If dict_only is True, grabs the dictionary of the WebSite from cache
        domain = WebPage.domain_for_url(WebPage.normalize_url(self.url))
        if dict_only is False:
            return WebSite().load({"domains": domain})
        else:
            sites = get_website_cache()
            for site in sites:
                if domain in site["domains"]:
                    return site
            return {}

    @staticmethod
    def normalize_url(url):
        rewrite_rules = {
            "use https": lambda url: re.sub(r"^http://", "https://", url),
            "remove hash": lambda url: re.sub(r"#.*", "", url),
            "remove url params": lambda url: re.sub(r"\?.+", "", url),
            "remove utm params": lambda url: re.sub(r"\?utm_.+", "", url),
            "remove fbclid param": lambda url: re.sub(r"\?fbclid=.+", "", url),
            "add www": lambda url: re.sub(r"^(https?://)(?!www\.)", r"\1www.", url),
            "remove www": lambda url: re.sub(r"^(https?://)www\.", r"\1", url),
            "remove mediawiki params": lambda url: re.sub(r"&amp;.+", "", url),
            "remove sort param": lambda url: re.sub(r"\?sort=.+", "", url),
            "remove all params after id": lambda url: re.sub(r"(\?id=\d+).+$", r"\1", url)
        }
        global_rules = ["remove hash", "remove utm params", "remove fbclid param"]
        domain = WebPage.domain_for_url(url)
        site_rules = global_rules
        site_data = WebPage.site_data_for_domain(domain)
        if site_data and site_data["is_whitelisted"]:
            site_rules += site_data.get("normalization_rules", [])
        for rule in site_rules:
            url = rewrite_rules[rule](url)

        return url

    @staticmethod
    def domain_for_url(url):
        return urlparse(url).netloc

    def should_be_excluded(self):
        """ Returns true if this webpage should not be included in our index
        because it matches a title/url we want to exclude or has no refs"""
        if len(self.refs) == 0:
            return True
        if len(self.url.encode('utf-8')) > 1000:
            # url field is indexed. Mongo doesn't allow indexing a field over 1000 bytes
            from sefaria.system.database import db
            db.webpages_long_urls.insert_one(self.contents())
            return True
        url_regex = WebPage.excluded_pages_url_regex()
        title_regex = WebPage.excluded_pages_title_regex()
        return bool(re.search(url_regex, self.url) or re.search(title_regex, self.title))

    @staticmethod
    def excluded_pages_url_regex():
        bad_urls = []
        sites = get_website_cache()
        for site in sites:
            bad_urls += site.get("bad_urls", [])
        return "({})".format("|".join(bad_urls))

    @staticmethod
    def excluded_pages_title_regex():
        bad_titles = [
            r"Page \d+ of \d+",  # Rabbi Sacks paged archives
            r"^Page not found$",   # JTS 404 pages include links to content
            r"^JTS Torah Online$"  # JTS search result pages
        ]
        return "({})".format("|".join(bad_titles))

    @staticmethod
    def site_data_for_domain(domain):
        sites = get_website_cache()
        for site in sites:
            for site_domain in site["domains"]:
                if site_domain == domain or domain.endswith("." + site_domain):
                    return site
        return None

    def update_from_linker(self, updates, existing=False):
        if existing and len(updates["title"]) == 0:
            # in case we are updating an existing web page that has a title,
            # we don't want to accidentally overwrite it with a blank title
            updates["title"] = self.title
        self.load_from_dict(updates)
        self.linkerHits += 1
        self.lastUpdated = datetime.now()
        self.save()

    @staticmethod
    def add_or_update_from_linker(data):
        """Adds an entry for the WebPage represented by `data` or updates an existing entry with the same normalized URL
        Returns True is data was saved, False if data was determined to be exluded"""
        data["url"] = WebPage.normalize_url(data["url"])
        webpage = WebPage().load(data["url"])
        if webpage:
            existing = True
        else:
            webpage = WebPage(data)
            existing = False
        webpage._normalize() # to remove bad refs, so pages with empty ref list aren't saved
        if webpage.should_be_excluded():
            if existing:
                webpage.delete()
            return "excluded"
        webpage.update_from_linker(data, existing)
        return "saved"

    def client_contents(self):
        d = self.contents()
        d["domain"]     = self.domain
        d["siteName"]   = self.site_name
        d["faviconUrl"] = self.favicon
        del d["lastUpdated"]
        d = self.clean_client_contents(d)
        return d

    def clean_client_contents(self, d):
        d["title"]       = self.clean_title()
        d["description"] = self.clean_description()
        return d

    def clean_title(self):
        if not self._site_data:
            return self.title
        title = str(self.title)
        title = title.replace("&amp;", "&")
        brands = [self.site_name] + self._site_data.get("title_branding", [])
        separators = [("-", ' '), ("|", ' '), ("—", ' '), ("–", ' '), ("»", ' '), ("•", ' '), (":", ''), ("⋆", ' ')]
        for separator, padding in separators:
            for brand in brands:
                if self._site_data.get("initial_title_branding", False):
                    brand_str = f"{brand}{padding}{separator} "
                    if title.startswith(brand_str):
                        title = title[len(brand_str):]
                else:
                    brand_str = f" {separator}{padding}{brand}"
                    if title.endswith(brand_str):
                        title = title[:-len(brand_str)]

        return title if len(title) else self._site_data["name"]

    def clean_description(self):
        description = self.description
        for uhoh_string in ["*/", "*******"]:
            if description.find(uhoh_string) != -1:
                return None
        description = description.replace("&amp;", "&")
        description = description.replace("&nbsp;", " ")
        return description


class WebPageSet(abst.AbstractMongoSet):
    recordClass = WebPage


class WebSite(abst.AbstractMongoRecord):
    collection = 'websites'

    required_attrs = [
        "name",
        "domains",
        "is_whitelisted"
    ]
    optional_attrs = [
        "bad_urls",
        "normalization_rules",
        "title_branding",
        "initial_title_branding",
        "linker_installed",
        "num_webpages",
        "exclude_from_tracking"
    ]

    def __key(self):
        return (self.name, self.domains[0])

    def __hash__(self):
        return hash(self.__key())

    def __eq__(self, other):
        if isinstance(other, WebSite):
            return self.__key() == other.__key()
        return NotImplemented


class WebSiteSet(abst.AbstractMongoSet):
    recordClass = WebSite


def get_website_cache():
    sites = in_memory_cache.get("websites_data")
    if sites in [None, []]:
        sites = [w.contents() for w in WebSiteSet()]
        in_memory_cache.set("websites_data", sites)
        return sites
    return sites


def get_webpages_for_ref(tref):
    from pymongo.errors import OperationFailure
    oref = text.Ref(tref)
    segment_refs = [r.normal() for r in oref.all_segment_refs()]
    results = WebPageSet(query={"expandedRefs": {"$in": segment_refs}}, hint="expandedRefs_1", sort=None)
    try:
        results = results.array()
    except OperationFailure as e:
        # If documents are too large or there are too many results, fail gracefully
        logger.warn(f"WebPageSet for ref {tref} failed due to Error: {repr(e)}")
        return []
    webpage_objs = {}      # webpage_obj is an actual WebPage()
    webpage_results = {}  # webpage_results is dictionary that API returns
    
    for webpage in results:
        if not webpage.whitelisted or len(webpage.title) == 0:
            continue
          
        webpage_key = webpage.title+"|".join(sorted(webpage.refs))+getattr(webpage, "description", "")
        prev_webpage_obj = webpage_objs.get(webpage_key, None)
        if prev_webpage_obj is None or prev_webpage_obj.lastUpdated < webpage.lastUpdated:
            anchor_ref_list, anchor_ref_expanded_list = oref.get_all_anchor_refs(segment_refs, webpage.refs,
                                                                                 webpage.expandedRefs)
            for anchor_ref, anchor_ref_expanded in zip(anchor_ref_list, anchor_ref_expanded_list):
                webpage_contents = webpage.client_contents()
                webpage_contents["anchorRef"] = anchor_ref.normal()
                webpage_contents["anchorRefExpanded"] = [r.normal() for r in anchor_ref_expanded]
                webpage_objs[webpage_key] = webpage
                webpage_results[webpage_key] = webpage_contents

    return list(webpage_results.values())


def test_normalization():
    pages = WebPageSet()
    count = 0
    for page in pages:
        norm = WebPage.normalize_url(page.url)
        if page.url != norm:
            print(page.url.encode("utf-8"))
            print(norm.encode("utf-8"))
            print("\n")
            count += 1

    print("{} pages normalized".format(count))


def dedupe_webpages(test=True):
    """Normalizes URLs of all webpages and deletes multiple entries that normalize to the same URL"""
    norm_count = 0
    dedupe_count = 0
    webpages = WebPageSet({"url": {"$regex": "why-learn-gemara"}})
    for i, webpage in enumerate(webpages):
        if i % 100000 == 0:
            print(i)
        norm = WebPage.normalize_url(webpage.url)
        if webpage.url != norm:
            normpage = WebPage().load(norm)
            if normpage:
                dedupe_count += 1
                if test:
                    print("DEDUPE")
                    print(webpage.url.encode("utf-8"))
                    print(norm.encode("utf-8"))
                    print("\n")
                else:
                    normpage.linkerHits += webpage.linkerHits
                    if normpage.lastUpdated < webpage.lastUpdated:
                        normpage.lastUpdated = webpage.lastUpdated
                        normpage.refs = webpage.refs
                        normpage.expandedRefs = webpage.expandedRefs
                    normpage.save()
                    webpage.delete()

            else:
                norm_count += 1
                if test:
                    print("NORM")
                    print(webpage.url.encode("utf-8"))
                    print(norm.encode("utf-8"))
                    print("\n")
                else:
                    webpage.save()
    print("{} pages removed as duplicates".format(dedupe_count))
    print("{} pages normalized".format(norm_count))

    dedupe_identical_urls(test=test)


def dedupe_identical_urls(test=True):
    dupes = db.webpages.aggregate([
        {"$group": {
            "_id": "$url",
            "uniqueIds": {"$addToSet": "$_id"},
            "count": {"$sum": 1}
            }
        },
        {"$match": {
            "count": {"$gt": 1}
            }
        },
        {"$sort": {
            "count": -1
            }
        }
    ], allowDiskUse=True);

    url_count = 0
    removed_count = 0
    for dupe in dupes:
        url_count += 1
        pages = WebPageSet({"_id": {"$in": dupe["uniqueIds"]}})
        merged_page_data = {
            "url": dupe["_id"], "linkerHits": 0, "lastUpdated": datetime.min
        }
        if test:
            print("\nReplacing: ")
        for page in pages:
            if test:
                print(page.contents())
            merged_page_data["linkerHits"] += page.linkerHits
            if merged_page_data["lastUpdated"] < page.lastUpdated:
                merged_page_data.update({
                    "refs": page.refs,
                    "expandedRefs": page.expandedRefs,
                    "title": page.title,
                    "description": page.description
                })
        removed_count += (pages.count() - 1)

        merged_page = WebPage(merged_page_data)
        if test:
            print("with")
            print(merged_page.contents())
        else:
            pages.delete()
            merged_page.save()

    print("\n{} pages with identical urls removed from {} url groups.".format(removed_count, url_count))


def clean_webpages(test=True):
    """ Delete webpages matching patterns deemed not worth including"""
    pages = WebPageSet({"$or": [
            {"url": {"$regex": WebPage.excluded_pages_url_regex()}},
            {"title": {"$regex": WebPage.excluded_pages_title_regex()}},
            {"refs": {"$eq": []}}
        ]})

    if not test:
        pages.delete()
        print("Deleted {} pages.".format(pages.count()))
    else:
        for page in pages:
            print(page.url)
        print("\n {} pages would be deleted".format(pages.count()))



def webpages_stats():
    webpages = WebPageSet()
    total_pages  = webpages.count()
    total_links  = []
    websites = {}

    for webpage in webpages:
        website = webpage.get_website()
        if website:
            if website not in websites:
                websites[website] = 0
            websites[website] += 1
        total_links += webpage.refs

    total_links = len(set(total_links))

    for website, num in websites.items():
        website.num_webpages = num
        website.save()

    return (total_pages, total_links)


def find_webpages_without_websites(test=True, hit_threshold=50, last_linker_activity_day=20):
    from datetime import datetime, timedelta
    webpages = WebPageSet()
    new_active_sites = Counter()   # WebSites we don't yet have in DB, but we have corresponding WebPages accessed recently
    unactive_unacknowledged_sites = {}  # WebSites we don't yet have in DB, and we have correpsonding WebPages but they have not been accessed recently
    last_active_threshold = datetime.today() - timedelta(days=last_linker_activity_day)

    for i, webpage in enumerate(webpages):
        if i % 100000 == 0:
            print(i)
        updated_recently = webpage.lastUpdated > last_active_threshold
        website = webpage.get_website(dict_only=True)
        if website == {} and len(webpage.domain.strip()) > 0:
            if updated_recently:
                new_active_sites[webpage.domain] += 1
            else:
                if webpage.domain not in unactive_unacknowledged_sites:
                    unactive_unacknowledged_sites[webpage.domain] = []
                unactive_unacknowledged_sites[webpage.domain].append(webpage)

    sites_added = []
    for site, hits in new_active_sites.items():
        if hits > hit_threshold:
            newsite = WebSite()
            newsite.name = site
            newsite.domains = [site]
            newsite.is_whitelisted = True
            newsite.linker_installed = True
            if not test:
                newsite.save()
            print("Created new WebSite with name='{}'".format(site))
            sites_added.append(site)

    print(sites_added)
    print("****")
    for site, hits in unactive_unacknowledged_sites.items():
        if site not in sites_added:  # if True, site has not been updated recently
            print("Deleting {} with {} pages".format(site, len(unactive_unacknowledged_sites[site])))
            for webpage in unactive_unacknowledged_sites[site]:
                if not test:
                    webpage.delete()


def find_sites_to_be_excluded(flag=100):
    all_sites = {}
    for i, webpage in enumerate(WebPageSet()):
        if i % 100000 == 0:
            print(i)
        website = webpage.get_website(dict_only=True)
        if website != {}:
            if website["name"] not in all_sites:
                all_sites[website["name"]] = Counter()
            for ref in webpage.refs:
                all_sites[website["name"]][ref] += 1

    for website in all_sites:
        if len(all_sites[website]) > 0:
            most_common = all_sites[website].most_common(10)
            for common in most_common:
                if common[1] > flag:
                    print("{} may need exclusions set because of ref {} with count {}".format(website, common[0], common[1]))

    #check_daf_yomi_and_parashat_hashavua(all_sites)

def check_daf_yomi_and_parashat_hashavua(sites):
    previous = datetime.now() - timedelta(10)
    recent_daf = daf_yomi(previous)[0]["ref"]
    recent_parasha = parashat_hashavua_and_haftara(previous)[0]["ref"]

    future_daf = datetime.now() + timedelta(500)
    future_daf = daf_yomi(future_daf)[0]["ref"]

    future_parasha = datetime.now() + timedelta(180)
    future_parasha = parashat_hashavua_and_haftara(future_parasha)[0]["ref"]
    poss_issues = {}
    for site in sites:
        poss_issues[site] = {}
        poss_issues[site]["Daf"] = 0
        poss_issues[site]["Parasha"] = 0
        for type, future, recent in [("Daf", future_daf, recent_daf), ("Parasha", future_parasha, recent_parasha)]:
            future_range = text.Ref(future)
            recent_range = text.Ref(recent)
            for ref, count in sites[site].items():
                try:
                    ref = text.Ref(ref)
                    if recent_range.contains(ref):
                        poss_issues[site][type] += count
                    if future_range.contains(ref):
                        poss_issues[site][type] -= count
                except InputError as e:
                    print(e)

    for site in poss_issues:
        daf = poss_issues[site]["Daf"]
        parasha = poss_issues[site]["Parasha"]
        if daf > 10:
            print("{} may have daf yomi on every page.".format(site))
        if parasha > 10:
            print("{} may have parasha on every page.".format(site))




def find_sites_that_may_have_removed_linker(test=True, last_linker_activity_day=20):
    """
    Checks for each site whether there has been a webpage hit with the linker in the last `last_linker_activity_day` days
    Prints an alert for each site that doesn't meet this criterion
    """
    from datetime import datetime, timedelta
    last_active_threshold = datetime.today() - timedelta(days=last_linker_activity_day)

    for data in get_website_cache():
     if data["is_whitelisted"]:  # we only care about whitelisted sites
        for domain in data['domains']:
            ws = WebPageSet({"url": {"$regex": re.escape(domain)}}, limit=1, sort=[['lastUpdated', -1]])
            if ws.count() == 0:
                print(f"Alert! {domain} has no pages")
            else:
                webpage = ws.array()[0]  # lastUpdated webpage for this domain
                website = webpage.get_website()
                if website:
                    website.linker_installed = webpage.lastUpdated > last_active_threshold
                    if not website.linker_installed:
                        print(f"Alert! {domain} has removed the linker!")
                    if not test:
                        website.save()
                else:
                    print("Alert! Can't find website {} corresponding to webpage {}".format(data["name"], webpage.url))
