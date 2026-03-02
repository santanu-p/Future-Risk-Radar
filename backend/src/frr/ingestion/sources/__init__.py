"""Ingestion sources package — registry of all data source clients."""

from frr.ingestion.sources.fred import FREDClient
from frr.ingestion.sources.eia import EIAClient
from frr.ingestion.sources.acled import ACLEDClient
from frr.ingestion.sources.ucdp import UCDPClient
from frr.ingestion.sources.nsf import NSFClient
from frr.ingestion.sources.uspto import USPTOClient
from frr.ingestion.sources.uncomtrade import UNComtradeClient
from frr.ingestion.sources.gdelt import GDELTClient
from frr.ingestion.sources.wipo import WIPOClient
from frr.ingestion.sources.epo import EPOClient
from frr.ingestion.sources.sipri import SIPRIClient
from frr.ingestion.sources.wto import WTOClient
from frr.ingestion.sources.freightos import FreightosClient
from frr.ingestion.sources.entsoe import ENTSOEClient
from frr.ingestion.sources.unhcr import UNHCRClient

# Source registry — add new clients here
ALL_SOURCES = [
    # Phase 1 sources (8)
    FREDClient,
    EIAClient,
    ACLEDClient,
    UCDPClient,
    NSFClient,
    USPTOClient,
    UNComtradeClient,
    GDELTClient,
    # Phase 2 sources (7)
    WIPOClient,
    EPOClient,
    SIPRIClient,
    WTOClient,
    FreightosClient,
    ENTSOEClient,
    UNHCRClient,
]

__all__ = [
    "ALL_SOURCES",
    "FREDClient",
    "EIAClient",
    "ACLEDClient",
    "UCDPClient",
    "NSFClient",
    "USPTOClient",
    "UNComtradeClient",
    "GDELTClient",
    "WIPOClient",
    "EPOClient",
    "SIPRIClient",
    "WTOClient",
    "FreightosClient",
    "ENTSOEClient",
    "UNHCRClient",
]
