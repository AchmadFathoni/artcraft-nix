{
  description = "ArtCraft apps (storytold) for Nix/NixOS, every release mirrored to GitHub and GitLab";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
    in
    {
      packages.${system} = import ./default.nix { pkgs = nixpkgs.legacyPackages.${system}; };

      # pkgs.artcraft.<app> built against your own nixpkgs.
      overlays.default = final: _prev: {
        artcraft = import ./default.nix { pkgs = final; };
      };

      # programs.artcraft.enable = true; see module.nix.
      nixosModules.default = ./module.nix;
    };
}
