"""
Run scrapy spiders from a script.

Blocks and runs all requests in parallel.  Accumulated items from all
spiders are returned as a list.
"""

import collections
import inspect

import os
if os.getenv("USE_SCRAPY_MULTIPROCESSING") is not None:
    from multiprocessing import Process  # fork of multiprocessing that works with celery
    from multiprocessing.queues import Queue
else:
    from billiard import Process  # fork of multiprocessing that works with celery
    from billiard.queues import Queue
import logging

from pydispatch import dispatcher
from scrapy import signals
from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings
from scrapy.spiders import Spider


class ScrapyScriptException(Exception):
    pass


class Job(object):
    """A job is a single request to call a specific spider. *args and **kwargs
    will be passed to the spider constructor.
    """

    def __init__(self, spider, *args, **kwargs):
        """Parms:
          spider (spidercls): the spider to be run for this job.
        """
        self.spider = spider
        self.args = args
        self.kwargs = kwargs


class Processor(Process):
    """ Start a twisted reactor and run the provided scrapy spiders.
    Blocks until all have finished.
    """

    def __init__(self, settings=None):
        """
        Parms:
          settings (scrapy.settings.Settings) - settings to apply.  Defaults
        to Scrapy default settings.
        """
        kwargs = {"ctx": __import__("billiard.synchronize")}

        self.results = Queue(**kwargs)
        self.items = []
        self.settings = settings or Settings()
        dispatcher.connect(self._item_scraped, signals.item_scraped)

    def _item_scraped(self, item):
        self.items.append(item)

    def _crawl(self, requests):
        """
        Parameters:
            requests (Request) - One or more Jobs. All will
                                 be loaded into a single invocation of the reactor.
        """
        logging.info("_crawl started")
        self.crawler = CrawlerProcess(self.settings)
        logging.info("CrawlerProcess created")

        # crawl can be called multiple times to queue several requests
        for req in requests:
            self.crawler.crawl(req.spider, *req.args, **req.kwargs)
            logging.info("self.crawler.crawl(req.spider, *req.args, **req.kwargs)")

        self.crawler.start()
        logging.info("self.crawler.start()")

        self.crawler.stop()
        logging.info("self.crawler.stop()")

        self.results.put(self.items)
        logging.info("self.results.put(self.items) " + str(self.items))

    def run(self, jobs):
        """Start the Scrapy engine, and execute all jobs.  Return consolidated results
        in a single list.

        Parms:
          jobs ([Job]) - one or more Job objects to be processed.

        Returns:
          List of objects yielded by the spiders after all jobs have run.
        """
        logging.info("run called")

        if not isinstance(jobs, collections.abc.Iterable):
            jobs = [jobs]
        self.validate(jobs)
        logging.info("self.validate(jobs)")

        p = Process(target=self._crawl, args=[jobs])
        logging.info("Process(target=self._crawl, args=[jobs])")
        p.start()
        logging.info("p.start()")
        p.join()
        logging.info("p.join()")
        p.terminate()
        logging.info("p.terminate()")

        return self.results.get()

    def validate(self, jobs):
        if not all([isinstance(x, Job) for x in jobs]):
            raise ScrapyScriptException("scrapyscript requires Job objects.")
