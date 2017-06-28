from __future__ import unicode_literals

import frappe
from frappe.utils import cint, flt
from provider_fedex import get_fedex_packages_rate
from utils import get_state_code, get_country_code
from math import ceil
from shipment_management.doctype.shipping_package_rule.shipping_package_rule import find_packages

VALID_PACKAGING_TYPES = (
	"FEDEX_10KG_BOX",
	"FEDEX_25KG_BOX",
	"FEDEX_BOX",
	"FEDEX_ENVELOPE",
	"FEDEX_PAK",
	"FEDEX_TUBE",
	"YOUR_PACKAGING"
)

def get_rates(from_address, to_address, items, packaging_type="YOUR_PACKAGING"):
	"""Simple wrapper over fedex rating service.
	It takes the standard address field values for the from_ and to_ addresses
	to keep a consistent address api. Packaging is a list of items with only
	two foe;d requirements "item_code" and "qty". """

	# quick hack to package all items into one box for quick shipping quotations
	#packages = find_packages(items)
	packages = []
	package = {
		"weight_value": 0,
		"weight_units": "LB",
		"physical_packaging": "BOX",
		"group_package_count": 0,
		"insured_amount": 100
	}

	for itm in items:
		item = frappe.get_all("Item", fields=["name", "net_weight"], filters={ "item_code": itm.get("item_code") })
		if item and len(item) > 0:
			item = item[0]
			weight = flt(item.get("net_weight", 0))
			package["weight_value"] = package["weight_value"] + (weight * itm.get("qty", 1))
			package["group_package_count"] = package["group_package_count"] + itm.get("qty")

			if itm["item_code"].find("CIEM") > -1:
				package["insured_amount"] = package["insured_amount"] + (300 * itm.get("qty", 1))

	package["weight_value"] = ceil(package["weight_value"])
	if package["weight_value"] < 1:
		package["weight_value"] = 1

	packages.append(package)

	# to try and keep some form of standardization we'll minimally  require
	# a weight_value. Any other values will be passed as is to the rates service.
	surcharge = 0
	for package in packages:
		if package.get("weight_value", None) is None or \
		   package.get("weight_units", None) is None:
			raise frappe.exceptions.ValidationError("Missing weight_value data")

		#if not package.get("group_package_count"):
		# keep count on 1 as we don't care about package groups
		package["group_package_count"] = 1

		if not package.get("insured_amount"):
			package["insured_amount"] = 0

		if not package.get("physical_packaging"):
			package["physical_packaging"] = "BOX"

		surcharge = surcharge + package.get("surcharge", 0)


		if to_address.get("address_type") == "Office":
			to_address["residential"] = False
		elif to_address.get("address_type") == "Residential":
			to_address["residential"] = True

	args = dict(
		DropoffType='REGULAR_PICKUP',
		PackagingType=packaging_type,
		EdtRequestType='NONE',
		PaymentType='SENDER',
		ShipperStateOrProvinceCode=from_address.get("state"),
		ShipperPostalCode=from_address.get("pincode"),
		ShipperCountryCode=get_country_code(from_address.get("country")),
		RecipientStateOrProvinceCode=to_address.get("state"),
		RecipientPostalCode=to_address.get("pincode"),
		IsResidential = to_address.get("residential"),
		RecipientCountryCode=get_country_code(to_address.get("country")),
		package_list=packages,
		ignoreErrors=True
	)

	upcharge_doc = frappe.get_doc("Shipment Rate Settings", "Shipment Rate Settings")

	rates = get_fedex_packages_rate(**args)
	sorted_rates = []
	for rate in sorted(rates, key=lambda rate: rate["fee"]):
		rate["fee"] = rate["fee"] + surcharge
		
		if upcharge_doc.upcharge_type == "Percentage":
			rate["fee"] = rate["fee"] + (rate["fee"] * (upcharge_doc.upcharge/100))
		elif upcharge_doc.upcharge_type == "Actual":
			rate["fee"] = rate["fee"] + upcharge_doc.upcharge

		sorted_rates.append(rate)

	sorted_rates.append({u'fee': 0, u'name': u'PICK UP', u'label': u'FLORIDA HQ PICK UP'})

	return sorted_rates
