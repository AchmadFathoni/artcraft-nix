# NixOS module: installs the ArtCraft apps and exposes the system fonts at
# /usr/share/fonts, the only place their text tools look (not fontconfig).
{ config, lib, pkgs, ... }:

let
  cfg = config.programs.artcraft;
  artcraft = import ./default.nix { inherit pkgs; };
  apps = lib.attrNames (lib.importJSON ./versions.json).apps;
in
{
  options.programs.artcraft = {
    enable = lib.mkEnableOption "the ArtCraft apps";

    apps = lib.mkOption {
      type = lib.types.listOf (lib.types.enum (lib.attrNames artcraft));
      default = apps;
      example = [ "photocraft" "vectorcraft_0_4_0" ];
      description = "Apps to install: `<app>` for its newest release, `<app>_<x>_<y>_<z>` to pin a version.";
    };

    linkFonts = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Link /usr/share/fonts to the system fonts so the apps' text tools find them.";
    };
  };

  config = lib.mkIf cfg.enable (lib.mkMerge [
    { environment.systemPackages = map (app: artcraft.${app}) cfg.apps; }
    (lib.mkIf cfg.linkFonts {
      fonts.fontDir.enable = true;
      systemd.tmpfiles.rules = [
        "d /usr/share 0755 root root -"
        "L+ /usr/share/fonts - - - - /run/current-system/sw/share/X11/fonts"
      ];
    })
  ]);
}
