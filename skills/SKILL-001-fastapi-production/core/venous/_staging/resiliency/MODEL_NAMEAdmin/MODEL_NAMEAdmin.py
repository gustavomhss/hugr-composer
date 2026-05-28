from __future__ import annotations


class MODEL_NAMEAdmin(ModelAdmin, model=MODEL_NAME):
    """Admin view for the MODEL_NAME model."""
    column_exclude_list = ['hashed_password', 'secret_enc', 'entry_hash', 'prev_hash']
    column_sortable_list = '__all__'
    can_delete = CAN_DELETE_VALUE
    name = 'MODEL_NAME'
    name_plural = 'MODEL_PLURAL'
    icon = 'ICON_VALUE'
