# Bio Account Balance

## Overview

This module adds cumulative balance calculation functionality to `account.move.line` (Journal Items) in Odoo 16.

## Features

### Stored Balance Fields
- **Initial Balance** (`bio_initial_balance`): Balance BEFORE the current transaction
- **End Balance** (`bio_end_balance`): Balance AFTER the current transaction (including current)

### Dynamic Balance Fields (for Pivot View)
- **Opening Balance** (`bio_opening_by_partner`): Opening balance at START of filtered period
- **Closing Balance** (`bio_closing_by_partner`): Closing balance at END of filtered period

## Technical Implementation

### Architecture
The module uses a two-table approach for optimal performance:

1. **`bio.account.move.line.balance`** - Stores pre-calculated balances
   - `bio_initial_balance`: Cumulative balance before line
   - `bio_end_balance`: Cumulative balance after line
   - Linked 1:1 with `account.move.line`

2. **`account.move.line`** - Extended with balance fields
   - Computed fields that read from balance table
   - Dynamic fields calculated in `read_group()` for pivot view

### SQL Window Functions
Balances are calculated using PostgreSQL window functions:

```sql
SUM(debit - credit) OVER (
    PARTITION BY account_id, COALESCE(partner_id, 0)
    ORDER BY date, id
    ROWS BETWEEN UNBOUNDED PRECEDING AND ...
)
```

**Partitioning:** Separate balance calculations per `(account_id, partner_id)` combination.

### Incremental Updates
When a journal item changes, the module intelligently updates:
- The changed line
- ALL subsequent lines in the same partition
- Uses `date >= min_date` to find affected lines

### Dynamic Pivot Calculations
The `read_group()` override provides real-time balance calculations based on pivot filters:

```python
@api.model
def read_group(self, domain, fields, groupby, ...):
    # Convert Odoo domain to SQL WHERE clause
    # Execute optimized SQL to find first/last lines
    # Sum balances for partner grouping
```

**Performance optimization:** Direct SQL using `_where_calc()` instead of `search()`.

## Usage

### In Tree View
Balance columns appear automatically:
- Initial Balance (before transaction)
- End Balance (after transaction)

### In Pivot View
Available measures:
- **Initial Balance** / **End Balance**: For detailed line-by-line analysis
- **Opening Balance** / **Closing Balance**: For period analysis with date filters

**Formula validation:**
```
Opening Balance + SUM(Debit - Credit) = Closing Balance
```

### Grouping Scenarios

**Scenario 1: Partner → Account (with date filter)**
- Use: Initial Balance, End Balance
- Shows: Per-account balances within date range

**Scenario 2: Partner only (with date filter)**
- Use: Opening Balance, Closing Balance
- Shows: Total partner balance across all accounts

## Installation

1. Copy `bio_account_balance` to your addons directory
2. Update apps list in Odoo
3. Install "Bio Account Balance" module
4. Post-init hook will automatically calculate balances for existing data

## Dependencies
- `account` (Odoo base accounting)

## Database Structure

### New Table
- `bio_account_move_line_balance`: Stores pre-calculated balances

### New Columns in account_move_line
- `bio_initial_balance` (stored)
- `bio_end_balance` (stored)
- `bio_opening_by_partner` (non-stored, dynamic)
- `bio_closing_by_partner` (non-stored, dynamic)

## Manual Balance Recalculation

If balances become inconsistent, manually recalculate via:

**Menu:** Accounting → Configuration → Account Move Line Balance → "Reset and Update" button

This will:
1. TRUNCATE balance table
2. Recalculate using SQL window functions
3. Sync to main account_move_line table

## Performance Considerations

### Advantages
- ✅ Fast CRUD operations (only 2 fields stored)
- ✅ Incremental updates (only affected lines)
- ✅ Optimized SQL (direct WHERE clause, no intermediate recordsets)
- ✅ PostgreSQL-specific optimizations (DISTINCT ON, window functions)

### Trade-offs
- ⚠️ Pivot view slightly slower (dynamic calculation)
- ⚠️ Suitable for: high-write, low-read pivot usage

## Technical Details

### Window Function Frame
- `ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING`: Excludes current row (initial balance)
- `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`: Includes current row (end balance)

### Partition Key
- `PARTITION BY account_id, COALESCE(partner_id, 0)`: Separate calculations per account+partner
- `COALESCE(partner_id, 0)`: Handles NULL partners correctly

### Ordering
- `ORDER BY date, id`: Chronological order with deterministic tie-breaking

## Troubleshooting

### Balances don't match
Run manual recalculation: **Reset and Update** button

### Slow pivot view
Consider:
- Reducing date range filter
- Fewer grouping levels
- Using tree view for detailed analysis

### Missing columns after upgrade
Execute SQL manually:
```sql
ALTER TABLE account_move_line
ADD COLUMN IF NOT EXISTS bio_initial_balance NUMERIC;

ALTER TABLE account_move_line
ADD COLUMN IF NOT EXISTS bio_end_balance NUMERIC;
```

Then run "Reset and Update".

## Credits

- Module: Bio Account Balance
- Version: 16.0.1.0.0
- Issue: ODOO-834

## License
LGPL-3
