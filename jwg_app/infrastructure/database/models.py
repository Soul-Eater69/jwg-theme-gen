"""Database ORM models using SQLAlchemy for the value-stream catalogue.

Covers the value stream, its stages, the stage<->capability mapping, and the L3/L2
capability tables. The stage table has no value_stream_id; a stage belongs to a value
stream only through the mapping table (idp_sightline_value_stream_capability), which
also carries the L3 capability for that stage.
"""

import logging

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.ext.declarative import declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()


class ValueStreamModel(Base):
    """
    ORM model for the ValueStream table.

    Stores value stream records with active/inactive status.
    Only active records (value_stream_active='yes') are served via API.
    """

    __tablename__ = "idp_sightline_value_stream"
    __table_args__ = {"schema": "idp_impact_analyis"}

    value_stream_id = Column(
        String(11),
        primary_key=True,
        comment="Unique value stream identifier (format: VSR followed by 8 digits)",
    )
    value_stream_name = Column(
        String(500),
        nullable=True,
        comment="Internal name of the value stream",
    )
    value_stream_display_name = Column(
        String(500),
        nullable=True,
        comment="Display name of the value stream",
    )
    value_stream_description = Column(
        Text,
        nullable=True,
        comment="Detailed description of the value stream",
    )
    value_stream_trigger = Column(
        Text,
        nullable=True,
        comment="Trigger or initiating event for the value stream",
    )
    value_stream_stakeholders = Column(
        Text,
        nullable=True,
        comment="Stakeholders involved in the value stream",
    )
    value_stream_value_proposition = Column(
        Text,
        nullable=True,
        comment="Value proposition of the value stream",
    )
    value_stream_assumptions = Column(
        Text,
        nullable=True,
        comment="Assumptions related to the value stream",
    )
    value_stream_defined_terms = Column(
        Text,
        nullable=True,
        comment="Defined terms/glossary for the value stream",
    )
    url = Column(
        String(1000),
        nullable=True,
        comment="Documentation/Confluence link for the value stream",
    )
    value_stream_active = Column(
        String(10),
        nullable=False,
        default="yes",
        comment="Active status flag ('yes' or 'no')",
    )

    # Audit fields - created
    value_stream_created_by = Column(
        String(200),
        nullable=True,
        comment="Display name of the user who created the record",
    )
    value_stream_created_by_id = Column(
        String(100),
        nullable=True,
        comment="LAN ID of the user who created the record",
    )
    value_stream_created_by_email = Column(
        String(200),
        nullable=True,
        comment="Email of the user who created the record",
    )
    value_stream_created_date = Column(
        DateTime,
        nullable=True,
        comment="Timestamp when the record was created",
    )

    # Audit fields - modified
    value_stream_modified_by = Column(
        String(200),
        nullable=True,
        comment="Display name of the user who last modified the record",
    )
    value_stream_modified_by_id = Column(
        String(100),
        nullable=True,
        comment="LAN ID of the user who last modified the record",
    )
    value_stream_modified_by_email = Column(
        String(200),
        nullable=True,
        comment="Email of the user who last modified the record",
    )
    value_stream_modified_date = Column(
        DateTime,
        nullable=True,
        comment="Timestamp when the record was last modified",
    )

    def __repr__(self) -> str:
        return f"<ValueStreamModel(id={self.value_stream_id}, name={self.value_stream_name})>"


class ValueStreamStageModel(Base):
    """
    ORM model for the value stream stage table.

    Stages are global records (no value_stream_id); a stage is tied to a value stream
    only through the mapping table. Only active records are served.
    """

    __tablename__ = "idp_sightline_value_stream_stage"
    __table_args__ = {"schema": "idp_impact_analyis"}

    value_stream_stage_id = Column(
        String(50),
        primary_key=True,
        comment="Unique value stream stage identifier",
    )
    value_stream_stage_name = Column(
        String(500),
        nullable=True,
        comment="Internal name of the stage",
    )
    value_stream_stage_display_name = Column(
        String(500),
        nullable=True,
        comment="Display name of the stage",
    )
    value_stream_stage_description = Column(
        Text,
        nullable=True,
        comment="Detailed description of the stage",
    )
    value_stream_stage_entrance_criteria = Column(
        Text,
        nullable=True,
        comment="Entrance criteria for the stage",
    )
    value_stream_stage_exit_criteria = Column(
        Text,
        nullable=True,
        comment="Exit criteria for the stage",
    )
    value_stream_stage_stakeholders = Column(
        Text,
        nullable=True,
        comment="Stakeholders involved in the stage",
    )
    value_stream_stage_value_items = Column(
        Text,
        nullable=True,
        comment="Value items delivered by the stage",
    )
    url = Column(
        String(1000),
        nullable=True,
        comment="Documentation/Confluence link for the stage",
    )
    value_stream_stage_active = Column(
        String(10),
        nullable=False,
        default="yes",
        comment="Active status flag ('yes' or 'no')",
    )

    # Audit fields - created
    value_stream_stage_created_by = Column(
        String(200),
        nullable=True,
        comment="Display name of the user who created the record",
    )
    value_stream_stage_created_by_id = Column(
        String(100),
        nullable=True,
        comment="LAN ID of the user who created the record",
    )
    value_stream_stage_created_by_email = Column(
        String(200),
        nullable=True,
        comment="Email of the user who created the record",
    )
    value_stream_stage_created_date = Column(
        DateTime,
        nullable=True,
        comment="Timestamp when the record was created",
    )

    # Audit fields - modified
    value_stream_stage_modified_by = Column(
        String(200),
        nullable=True,
        comment="Display name of the user who last modified the record",
    )
    value_stream_stage_modified_by_id = Column(
        String(100),
        nullable=True,
        comment="LAN ID of the user who last modified the record",
    )
    value_stream_stage_modified_by_email = Column(
        String(200),
        nullable=True,
        comment="Email of the user who last modified the record",
    )
    value_stream_stage_modified_date = Column(
        DateTime,
        nullable=True,
        comment="Timestamp when the record was last modified",
    )

    def __repr__(self) -> str:
        return (
            f"<ValueStreamStageModel(id={self.value_stream_stage_id}, "
            f"name={self.value_stream_stage_name})>"
        )


class ValueStreamCapabilityModel(Base):
    """
    ORM model for the value stream <-> stage <-> capability mapping table.

    Each row links a value stream, one of its stages, and an L3 capability (capability_id
    joins idp_sightline_l3_capabilities.l3_capability_id). This is the only link between a
    value stream and its stages. Value stream / stage / capability names are denormalized here.
    """

    __tablename__ = "idp_sightline_value_stream_capability"
    __table_args__ = {"schema": "idp_impact_analyis"}

    id = Column(
        String(50),
        primary_key=True,
        comment="Unique mapping row identifier",
    )
    value_stream_id = Column(
        String(11),
        nullable=True,
        comment="Value stream this mapping belongs to",
    )
    value_stream_name = Column(
        String(500),
        nullable=True,
        comment="Denormalized value stream name",
    )
    value_stream_display_name = Column(
        String(500),
        nullable=True,
        comment="Denormalized value stream display name",
    )
    value_stream_stage_id = Column(
        String(50),
        nullable=True,
        comment="Stage this mapping belongs to",
    )
    value_stream_stage_name = Column(
        String(500),
        nullable=True,
        comment="Denormalized stage name",
    )
    value_stream_stage_display_name = Column(
        String(500),
        nullable=True,
        comment="Denormalized stage display name",
    )
    capability_id = Column(
        String(50),
        nullable=True,
        comment="L3 capability mapped to the stage (joins idp_sightline_l3_capabilities.l3_capability_id)",
    )
    capability_name = Column(
        String(500),
        nullable=True,
        comment="Denormalized capability name",
    )
    capability_display_name = Column(
        String(500),
        nullable=True,
        comment="Denormalized capability display name",
    )

    def __repr__(self) -> str:
        return (
            f"<ValueStreamCapabilityModel(value_stream_id={self.value_stream_id}, "
            f"stage_id={self.value_stream_stage_id}, capability_id={self.capability_id})>"
        )


class L3CapabilityModel(Base):
    """
    ORM model for the L3 (leaf) capability table.

    parent_capability_id points at the owning L2 capability
    (idp_sightline_l2_capabilities.l2_capability_id). Only active records are served.
    """

    __tablename__ = "idp_sightline_l3_capabilities"
    __table_args__ = {"schema": "idp_impact_analyis"}

    l3_capability_id = Column(
        String(50),
        primary_key=True,
        comment="Unique L3 capability identifier",
    )
    capability_name = Column(
        String(500),
        nullable=True,
        comment="Internal name of the capability",
    )
    capability_display_name = Column(
        String(500),
        nullable=True,
        comment="Display name of the capability",
    )
    capability_description = Column(
        Text,
        nullable=True,
        comment="Detailed description of the capability",
    )
    parent_capability_id = Column(
        String(50),
        nullable=True,
        comment="Parent L2 capability id (joins idp_sightline_l2_capabilities.l2_capability_id)",
    )
    capability_level = Column(
        String(50),
        nullable=True,
        comment="Capability hierarchy level",
    )
    capability_tier = Column(
        String(50),
        nullable=True,
        comment="Capability tier",
    )
    bus_obj_nm = Column(
        String(500),
        nullable=True,
        comment="Business object name",
    )
    bus_obj_desc = Column(
        Text,
        nullable=True,
        comment="Business object description",
    )
    bcm_ord_cd = Column(
        String(50),
        nullable=True,
        comment="BCM order code",
    )
    clarifying_cmt = Column(
        Text,
        nullable=True,
        comment="Clarifying comment",
    )
    url = Column(
        String(1000),
        nullable=True,
        comment="Documentation/Confluence link for the capability",
    )
    capability_active = Column(
        String(10),
        nullable=False,
        default="yes",
        comment="Active status flag ('yes' or 'no')",
    )

    # Audit fields - created
    capability_created_by = Column(
        String(200),
        nullable=True,
        comment="Display name of the user who created the record",
    )
    capability_created_by_id = Column(
        String(100),
        nullable=True,
        comment="LAN ID of the user who created the record",
    )
    capability_created_by_email = Column(
        String(200),
        nullable=True,
        comment="Email of the user who created the record",
    )
    capability_created_date = Column(
        DateTime,
        nullable=True,
        comment="Timestamp when the record was created",
    )

    # Audit fields - modified
    capability_modified_by = Column(
        String(200),
        nullable=True,
        comment="Display name of the user who last modified the record",
    )
    capability_modified_by_id = Column(
        String(100),
        nullable=True,
        comment="LAN ID of the user who last modified the record",
    )
    capability_modified_by_email = Column(
        String(200),
        nullable=True,
        comment="Email of the user who last modified the record",
    )
    capability_modified_date = Column(
        DateTime,
        nullable=True,
        comment="Timestamp when the record was last modified",
    )

    def __repr__(self) -> str:
        return f"<L3CapabilityModel(id={self.l3_capability_id}, name={self.capability_name})>"


class L2CapabilityModel(Base):
    """
    ORM model for the L2 capability table.

    parent_capability_id points at the owning L1 capability
    (idp_sightline_l1_capabilities.l1_capability_id). Only active records are served.
    """

    __tablename__ = "idp_sightline_l2_capabilities"
    __table_args__ = {"schema": "idp_impact_analyis"}

    l2_capability_id = Column(
        String(50),
        primary_key=True,
        comment="Unique L2 capability identifier",
    )
    capability_name = Column(
        String(500),
        nullable=True,
        comment="Internal name of the capability",
    )
    capability_display_name = Column(
        String(500),
        nullable=True,
        comment="Display name of the capability",
    )
    capability_description = Column(
        Text,
        nullable=True,
        comment="Detailed description of the capability",
    )
    parent_capability_id = Column(
        String(50),
        nullable=True,
        comment="Parent L1 capability id (joins idp_sightline_l1_capabilities.l1_capability_id)",
    )
    capability_level = Column(
        String(50),
        nullable=True,
        comment="Capability hierarchy level",
    )
    capability_tier = Column(
        String(50),
        nullable=True,
        comment="Capability tier",
    )
    bus_obj_nm = Column(
        String(500),
        nullable=True,
        comment="Business object name",
    )
    bus_obj_desc = Column(
        Text,
        nullable=True,
        comment="Business object description",
    )
    bcm_ord_cd = Column(
        String(50),
        nullable=True,
        comment="BCM order code",
    )
    clarifying_cmt = Column(
        Text,
        nullable=True,
        comment="Clarifying comment",
    )
    url = Column(
        String(1000),
        nullable=True,
        comment="Documentation/Confluence link for the capability",
    )
    capability_active = Column(
        String(10),
        nullable=False,
        default="yes",
        comment="Active status flag ('yes' or 'no')",
    )

    # Audit fields - created
    capability_created_by = Column(
        String(200),
        nullable=True,
        comment="Display name of the user who created the record",
    )
    capability_created_by_id = Column(
        String(100),
        nullable=True,
        comment="LAN ID of the user who created the record",
    )
    capability_created_by_email = Column(
        String(200),
        nullable=True,
        comment="Email of the user who created the record",
    )
    capability_created_date = Column(
        DateTime,
        nullable=True,
        comment="Timestamp when the record was created",
    )

    # Audit fields - modified
    capability_modified_by = Column(
        String(200),
        nullable=True,
        comment="Display name of the user who last modified the record",
    )
    capability_modified_by_id = Column(
        String(100),
        nullable=True,
        comment="LAN ID of the user who last modified the record",
    )
    capability_modified_by_email = Column(
        String(200),
        nullable=True,
        comment="Email of the user who last modified the record",
    )
    capability_modified_date = Column(
        DateTime,
        nullable=True,
        comment="Timestamp when the record was last modified",
    )

    def __repr__(self) -> str:
        return f"<L2CapabilityModel(id={self.l2_capability_id}, name={self.capability_name})>"
