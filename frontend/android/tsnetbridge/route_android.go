//go:build android

package tsnetbridge

import "tailscale.com/net/netmon"

func notifyDefaultRouteInterface(ifName string) {
	netmon.UpdateLastKnownDefaultRouteInterface(ifName)
}

