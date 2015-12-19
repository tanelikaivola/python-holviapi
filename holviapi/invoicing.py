# -*- coding: utf-8 -*-
from __future__ import print_function
import six
from future.utils import python_2_unicode_compatible, raise_from
import datetime
from decimal import Decimal
from .utils import HolviObject, JSONObject
from .categories import IncomeCategory, CategoriesAPI

class Invoice(HolviObject):
    """This represents an invoice in the Holvi system"""
    items = []
    issue_date = None
    due_date = None
    _valid_keys = ['currency', 'issue_date', 'due_date', 'items', 'receiver', 'type', 'number', 'subject'] # Same for both create and update

    def _map_holvi_json_properties(self):
        self.items = []
        for item in self._jsondata["items"]:
            self.items.append(InvoiceItem(self, holvi_dict=item))
        self.issue_date = datetime.datetime.strptime(self._jsondata["issue_date"], "%Y-%m-%d").date()
        self.due_date = datetime.datetime.strptime(self._jsondata["due_date"], "%Y-%m-%d").date()

    def _init_empty(self):
        """Creates the base set of attributes invoice has/needs"""
        self._jsondata = {
            "code": None,
            "currency": "EUR",
            "subject": "",
            "due_date": (datetime.datetime.now().date() + datetime.timedelta(days=14)).isoformat(),
            "issue_date": datetime.datetime.now().date().isoformat(),
            "number": None,
            "type": "outbound",
            "receiver": {
                "name": "",
                "email": "",
                "street": "",
                "city": "",
                "postcode": "",
                "country": ""
            },
            "items": [],
        }

    def send(self, send_email=True):
        """Marks the invoice as sent in Holvi

        If send_email is False then the invoice is *not* automatically emailed to the recipient
        and your must take care of sending the invoice yourself.
        """
        url = six.u(self.api.base_url + '{code}/status/').format(code=self.code)
        payload = {
            'mark_as_sent': True,
            'send_email': send_email,
            'active': True, # It must be active to be sent...
        }
        stat = self.api.connection.make_put(url, payload)
        #print("Got stat=%s" % stat)
        # TODO: Check the stat and raise error if daft is not false or active is not true ?

    def to_holvi_dict(self):
        """Convert our Python object to JSON acceptable to Holvi API"""
        self._jsondata["items"] = []
        for item in self.items:
            self._jsondata["items"].append(item.to_holvi_dict())
        self._jsondata["issue_date"] = self.issue_date.isoformat()
        self._jsondata["due_date"] = self.due_date.isoformat()
        return { k:v for (k,v) in self._jsondata.items() if k in self._valid_keys }

    def save(self):
        """Saves this invoice to Holvi, returns the created/updated invoice"""
        if not self.items:
            raise HolviError("No items")
        if not self.subject:
            raise HolviError("No subject")
        send_json = self.to_holvi_dict()
        if self.code:
            #print("Updating invoice %s" % self.code)
            url = six.u(self.api.base_url + '{code}/').format(code=self.code)
            stat = self.api.connection.make_put(url, send_json)
            #print("Got stat=%s" % stat)
            return Invoice(self.api, stat)
        else:
            #print("Creating new invoice %s" % send_json["subject"])
            url = six.u(self.api.base_url)
            stat = self.api.connection.make_post(url, send_json)
            #print("Got stat=%s" % stat)
            return Invoice(self.api, stat)


class InvoiceItem(JSONObject): # We extend JSONObject instead of HolviObject since there is no direct way to manipulate these
    """Pythonic wrapper for the items in an Invoice"""
    api = None
    invoice = None
    category = None
    net = None
    gross = None
    _cklass = IncomeCategory
    _valid_keys = ['detailed_price', 'category', 'description'] # Same for both create and update

    def __init__(self, invoice, holvi_dict={}, cklass=None):
        self.invoice = invoice
        self.api = self.invoice.api
        if cklass:
            self._cklass = cklass
        super(InvoiceItem, self).__init__(**holvi_dict)
        self._map_holvi_json_properties()

    def _map_holvi_json_properties(self):
        if not self._jsondata.get("detailed_price"):
            self._jsondata["detailed_price"] = { "net": "0.00", "gross": "0.00" }
        self.net = Decimal(self._jsondata["detailed_price"].get("net"))
        self.gross = Decimal(self._jsondata["detailed_price"].get("gross"))
        if self._jsondata.get("category"):
            self.category = self._cklass(self.api.categories_api, {"code": self._jsondata["category"]})
        # PONDER: there is a 'product' key in the Holvi JSON for items but it's always None
        #         and the web UI does not allow setting products to invoices

    def to_holvi_dict(self):
        if not self.gross:
            self.gross = self.net
        if not self._jsondata.get("detailed_price"):
            self._jsondata["detailed_price"] = { "net": "0.00", "gross": "0.00" } #  "currency" and "vat_rate" are not sent to Holvi
        self._jsondata["detailed_price"]["net"] = self.net.quantize(Decimal(".01")).__str__() # six.u messes this up
        self._jsondata["detailed_price"]["gross"] = self.gross.quantize(Decimal(".01")).__str__() # six.u messes this up
        if self.category:
            self._jsondata["category"] = self.category.code
        filtered = { k:v for (k,v) in self._jsondata.items() if k in self._valid_keys }
        if "vat_rate" in filtered["detailed_price"]:
            del(filtered["detailed_price"]["vat_rate"])
        if "currency" in filtered["detailed_price"]:
            del(filtered["detailed_price"]["currency"])
        return filtered


@python_2_unicode_compatible
class InvoiceAPI(object):
    """Handles the operations on invoices, instantiate with a Connection object"""
    base_url_fmt = 'pool/{pool}/invoice/'

    def __init__(self, connection):
        self.connection = connection
        self.categories_api = CategoriesAPI(self.connection)
        self.base_url = six.u(connection.base_url_fmt + self.base_url_fmt).format(pool=connection.pool)

    def list_invoices(self):
        """Lists all invoices in the system"""
        # TODO add filtering support (if/when holvi adds it)
        invoices = self.connection.make_get(self.base_url)
        #print("Got invoices=%s" % invoices)
        ret = []
        for ijson in invoices:
            ret.append(Invoice(self, ijson))
        return ret

    def create_invoice(self, invoice):
        """Takes an Invoice and creates it to Holvi"""
        raise NotImplementedError()

    def get_invoice(self, invoice_code):
        """Retvieve given Invoice"""
        url = self.base_url + '{code}/'.format(code=invoice_code)
        ijson = self.connection.make_get(url)
        #print("Got ijson=%s" % ijson)
        return Invoice(self, ijson)
