# Civilization Revolution link

A small installer for playing Sid Meier's Civilization Revolution together on RPCS3. It installs the official emulator, writes one shared LAN Party configuration, and connects players through a private network hosted on one always-on machine.

The game and the PS3 firmware are not in this repository. Each person uses a firmware update they downloaded from Sony and a game image from a copy they own.

## What you need

- Windows or Linux
- Python 3.11 or newer
- WireGuard (`wireguard-tools` on Linux, the official Windows app from https://www.wireguard.com/install/)
- On Windows, 7-Zip, because the official RPCS3 build is a `.7z` archive
- The same game version on every machine. A 1.00 image and a 1.30 image can see each other and still fail to join

Civilization Revolution finds players with a LAN broadcast. It does not have a confirmed internet matchmaking service on RPCS3. This link gives every machine an address on `10.66.0.0/24` and repeats those broadcasts. The tunnel only carries that network. It does not send the rest of your traffic through the host.

## Host

On the machine that stays on, in this directory:

```bash
sudo ./install.sh --host --generate-passphrase
```

The command prints a room passphrase, a certificate fingerprint, and the public address friends should use. Forward UDP 51820 and TCP 51821 from the router to this machine. The passphrase is also stored in `/var/lib/civrev-link/passphrase.txt`, readable only by root.

## Everyone else

```bash
git clone <this repository>
cd civrev-link
./install.sh
```

On Windows, double-click `install.cmd` or run it from a prompt.

The installer detects the operating system and downloads the matching official build from the RPCS3 Linux or Windows release. It then asks for:

1. The PS3 system software `.pup` you downloaded from Sony
2. Your own game image or a folder dumped from your own copy
3. The host's public address, room passphrase, and certificate fingerprint

It does not download the game from anywhere.

## Playing

```bash
./play.sh
```

Windows: `play.cmd`.

One person opens Multiplayer, then LAN Party, and stays on that screen. The others join the game that appears. The host waits until everyone has joined before pressing Ready. Pressing Ready first makes the join fail.

The host machine can play too. Its emulator uses `10.66.0.1` and does not open a second tunnel. Run the player installer there after the host installer if you also want RPCS3 on that machine.

## Limits

Two computers on different networks seeing the LAN Party list is the test that this works against the game. If a lobby appears and then refuses the join, the game is advertising an address the repeater did not expect. The installer cannot fix that by itself.

This does not run a copy of the game for each friend on one computer. Each person runs RPCS3 on their own machine.
