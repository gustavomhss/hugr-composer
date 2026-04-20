from __future__ import annotations
from typing import Any


class SchemaComparator:
    """Diff two OpenAPI 3.x JSON schemas and classify the changes."""

    def compare(self, baseline: dict[str, Any], current: dict[str, Any]) -> ComparisonResult:
        """Compare baseline schema against current, return classified result.

        Args:
            baseline: Baseline OpenAPI schema dict (JSON-loaded).
            current: Current OpenAPI schema dict (JSON-loaded).

        Returns:
            ``ComparisonResult`` with classification and violation lists.
        """
        breaking: list[str] = []
        compatible: list[str] = []
        additive: list[str] = []
        self._compare_components(baseline, current, breaking, compatible, additive)
        self._compare_paths(baseline, current, breaking, compatible, additive)
        classification = self._classify(breaking, compatible, additive)
        summary = self._build_summary(classification, breaking, additive)
        return ComparisonResult(classification=classification, breaking=breaking, compatible=compatible, additive=additive, summary=summary)

    def _compare_components(self, baseline: dict[str, Any], current: dict[str, Any], breaking: list[str], compatible: list[str], additive: list[str]) -> None:
        """Compare OpenAPI components/schemas between baseline and current.

        Args:
            baseline: Baseline OpenAPI schema dict.
            current: Current OpenAPI schema dict.
            breaking: Accumulator for breaking violations.
            compatible: Accumulator for compatible change descriptions.
            additive: Accumulator for additive change descriptions.
        """
        base_schemas = baseline.get('components', {}).get('schemas', {})
        curr_schemas = current.get('components', {}).get('schemas', {})
        for name, base_schema in base_schemas.items():
            if name not in curr_schemas:
                breaking.append(f"BREAKING: schema '{name}' removed from components")
                continue
            curr_schema = curr_schemas[name]
            base_props = base_schema.get('properties', {})
            curr_props = curr_schema.get('properties', {})
            path = f'components.{name}'
            breaking.extend(check_fields_removed(base_props, curr_props, path))
            breaking.extend(check_types_changed(base_props, curr_props, path))
            breaking.extend(check_required_added(base_schema, curr_schema, path))
            breaking.extend(check_enum_shrunk(base_props, curr_props, path))
            for new_field in sorted(set(curr_props) - set(base_props)):
                additive.append(f"ADDITIVE: field '{path}.{new_field}' added")
        for name in sorted(set(curr_schemas) - set(base_schemas)):
            additive.append(f"ADDITIVE: schema '{name}' added to components")

    def _compare_paths(self, baseline: dict[str, Any], current: dict[str, Any], breaking: list[str], compatible: list[str], additive: list[str]) -> None:
        """Compare OpenAPI paths between baseline and current.

        Args:
            baseline: Baseline OpenAPI schema dict.
            current: Current OpenAPI schema dict.
            breaking: Accumulator for breaking violations.
            compatible: Accumulator for compatible change descriptions.
            additive: Accumulator for additive change descriptions.
        """
        base_paths = baseline.get('paths', {})
        curr_paths = current.get('paths', {})
        for path, base_item in base_paths.items():
            if path not in curr_paths:
                breaking.append(f"BREAKING: endpoint '{path}' removed")
                continue
            curr_item = curr_paths[path]
            for method in ('get', 'post', 'put', 'patch', 'delete'):
                base_op = base_item.get(method, {})
                curr_op = curr_item.get(method, {})
                if base_op and (not curr_op):
                    breaking.append(f"BREAKING: {method.upper()} '{path}' removed")
                    continue
                if base_op and curr_op:
                    base_resp = base_op.get('responses', {})
                    curr_resp = curr_op.get('responses', {})
                    op_path = f'{method.upper()} {path}'
                    breaking.extend(check_response_shape_changed(base_resp, curr_resp, op_path))
        for path in sorted(set(curr_paths) - set(base_paths)):
            additive.append(f"ADDITIVE: endpoint '{path}' added")

    def _classify(self, breaking: list[str], compatible: list[str], additive: list[str]) -> ChangeClass:
        """Classify diff into BREAKING/COMPATIBLE/ADDITIVE/IDENTICAL.

        Args:
            breaking: List of breaking violations.
            compatible: List of compatible changes.
            additive: List of additive changes.

        Returns:
            The most severe ``ChangeClass`` applicable.
        """
        if breaking:
            return ChangeClass.BREAKING
        if compatible:
            return ChangeClass.COMPATIBLE
        if additive:
            return ChangeClass.ADDITIVE
        return ChangeClass.IDENTICAL

    def _build_summary(self, classification: ChangeClass, breaking: list[str], additive: list[str]) -> str:
        """Build a concise one-line summary of the comparison result.

        Args:
            classification: Overall change classification.
            breaking: Breaking violation list.
            additive: Additive change list.

        Returns:
            Human-readable summary string.
        """
        if classification == ChangeClass.IDENTICAL:
            return 'Schemas are identical — no changes detected.'
        return f'{classification.value}: {len(breaking)} breaking, {len(additive)} additive changes.'
