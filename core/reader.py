"""
SublimeGerrit - full-featured Gerrit Code Review for Sublime Text

Copyright (C) 2015 Borys Forytarz <borys.forytarz@gmail.com>

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
"""

import sublime
import re
from .settings import Settings
from .utils import log

class ReaderConfigError(Exception):
    pass

class DataReader():
    def __init__(self, kind):
        self.kind = kind

    def get_by_path(self, data, path):
        if path:
            path = path.split('.')
            current = data

            for value in path:
                if re.match('^\d+$', value):
                    value = int(value)

                if value in current:
                    current = current[value];
                else:
                    return ''

            return current

        else:
            return data


    def map(self, records, mappings):
        ret = []

        if not isinstance(records, list):
            records = [records]

        for record in records:
            newRecord = {}

            if mappings:
                for mapping in mappings:
                    field_path = mappings[mapping]

                    if isinstance(field_path, dict):
                        newRecord.update({
                            mapping: self._read(
                                root=field_path['root'],
                                data=record,
                                mappings=field_path['mappings'],
                                group_by=field_path['group_by'] if 'group_by' in field_path else None
                            )
                        })

                    else:
                        newRecord.update({
                            mapping: self.get_by_path(record, field_path)
                        })

            ret.append(newRecord)

        return ret


    def _read(self, root, data, mappings, group_by):
        records = self.map(self.get_by_path(data, root), mappings)
        grouped = {}
        is_grouped = False

        records_length = len(records)

        for i in range(0, records_length):
            record = records[i]

            # for path in subModel:

            #     SubModelClass = subModel[path];
            #     subRecords = self.get_by_path(record, path)
            #     subRecordsLength = len(subRecords)

            #     for j in range(0, subRecordsLength):
            #         subRecords[j] = SubModelClass(subRecords[j])
                    # subRecords[j].getDataProvider = function () {
                    #     return self.dataProvider;
                    # };

            # groupValue;

            # records[i] = ModelClass(record)

            # records[i].getDataProvider = function () {
            #     return self.dataProvider;
            # };

            if group_by:
                group_value = self.get_by_path(records[i], group_by)

                if group_value:
                    is_grouped = True

                    if not group_value in grouped:
                        grouped.update({group_value: []})

                    grouped[group_value].append(records[i])

        return grouped if is_grouped else records


    def read(self, data, reader_name=None):
        if data is None or isinstance(data, str):
            return data

        config = None

        settings = sublime.load_settings('SublimeGerritReaders.sublime-settings')

        if reader_name is None:
            if isinstance(data, dict) and 'kind' in data:
                log('Got response kind: ', data['kind'])
                config = settings.get(data['kind'])
            elif isinstance(data, list) and len(data) > 0 and ('kind' in data[0] or self.kind):
                kind = ('kind' in data[0] and data[0]['kind']) or self.kind

                log('Got response kind: list of', kind)
                config = settings.get(kind)

            elif self.kind:
                config = settings.get(self.kind)
        else:
            log('Forcing reader for response:', reader_name)
            config = settings.get(reader_name)

        if not config:
            log('No reader for this kind configured, return as-is', data)
            return data

        root = config['root']
        mappings = config['mappings']
        group_by = config['group_by'] if 'group_by' in config else None

        result = None

        if isinstance(root, dict):
            result = {}

            for name in root:
                root = root[name]

                mappings = mappings[name] if isinstance(mappings, dict) else None
                group_by = group_by[name] if isinstance(group_by, dict) else None

                result.update({
                    name: self._read(root, data, mappings, group_by)
                })
        else:
            result = self._read(root, data, mappings, group_by)

        log('=====================================')
        log(result)

        return result

