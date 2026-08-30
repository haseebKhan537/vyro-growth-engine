from __future__ import annotations

SAMPLE_ORG_RECORD = {
    "number": "1487448189",
    "enumeration_type": "NPI-2",
    "basic": {
        "organization_name": "100 CHIRO CORONA LLC",
        "status": "A",
    },
    "addresses": [
        {
            "address_purpose": "LOCATION",
            "city": "AUSTIN",
            "state": "TX",
        }
    ],
    "taxonomies": [
        {
            "code": "111N00000X",
            "desc": "Chiropractor",
            "primary": True,
        }
    ],
}

SAMPLE_ORG_RECORD_2 = {
    "number": "1234567890",
    "enumeration_type": "NPI-2",
    "basic": {
        "organization_name": "AUSTIN FAMILY MEDICINE PLLC",
        "status": "A",
    },
    "addresses": [
        {
            "address_purpose": "LOCATION",
            "city": "AUSTIN",
            "state": "TX",
        }
    ],
    "taxonomies": [
        {
            "desc": "Family Medicine",
            "primary": True,
        }
    ],
}

MALFORMED_RECORDS = [
    {"enumeration_type": "NPI-2", "basic": {"organization_name": "Missing NPI"}},
    {
        "number": "1111111111",
        "enumeration_type": "NPI-2",
        "basic": {},
    },
    {
        "number": "2222222222",
        "enumeration_type": "NPI-1",
        "basic": {"first_name": "Jane", "last_name": "Doe"},
    },
]
