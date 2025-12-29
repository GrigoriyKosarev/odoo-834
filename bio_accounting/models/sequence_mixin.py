# -*- coding: utf-8 -*-

from odoo import models


class SequenceMixin(models.AbstractModel):
    _inherit = 'sequence.mixin'

    # def _get_sequence_format_param(self, previous):
    #     format_string, format_values = super()._get_sequence_format_param(previous)
    #     format_values['year_length'] = 2
    #     format_values['year'] = format_values['year'] % (10 ** format_values['year_length'])
    #     return format_string, format_values
