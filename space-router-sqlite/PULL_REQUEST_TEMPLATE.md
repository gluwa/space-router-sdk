# Add SQLite Support for Local Development

## Overview
This PR adds SQLite support as an alternative to Supabase for local development and testing. This makes it easier to set up and run Space Router locally without external dependencies.

## Changes

### Core Implementation
- Added `SQLiteClient` class that mirrors the `SupabaseClient` interface
- Created SQLite database schema that matches the Supabase tables
- Added configuration option `SR_USE_SQLITE` to switch between database backends
- Implemented proper SQLite query handling for different operations

### Improvements
- Modified route handlers to work properly with path-based routing
- Updated authentication and node selection to work with SQLite
- Fixed proxy authentication handling
- Added fallback logic for testing environments

### Documentation
- Updated README with SQLite configuration instructions
- Added environment variables for SQLite mode
- Included examples for both development and production deployments

## Testing
- Verified all components (coordination-api, proxy-gateway, home-node) work with SQLite
- Tested end-to-end request flow through the system
- Ensured all existing tests continue to pass

## Screenshots
None

## Additional Notes
The SQLite implementation maintains compatibility with the existing Supabase implementation, allowing projects to switch between the two based on deployment needs.