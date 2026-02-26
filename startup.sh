#!/usr/bin/env bash
# Start the SSH daemon
/usr/sbin/sshd

# Execute the main container command
exec "$@"