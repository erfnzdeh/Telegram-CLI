"""Terminal User Interface for interactive mode.

Provides an interactive menu-driven interface for the Telegram CLI.
Uses the `rich` library for beautiful terminal output.
"""

import asyncio
import sys
from typing import Optional, List, Tuple

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm, IntPrompt
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.text import Text
    from rich.style import Style
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from .config import ConfigManager
from .logger import ForwarderLogger
from .client import ClientWrapper


class TUI:
    """Terminal User Interface for Telegram CLI."""
    
    def __init__(self, config_manager: ConfigManager, logger: ForwarderLogger):
        """Initialize TUI.
        
        Args:
            config_manager: Config manager instance
            logger: Logger instance
        """
        if not RICH_AVAILABLE:
            raise ImportError(
                "TUI requires the 'rich' library. Install it with: pip install rich"
            )
        
        self.config_manager = config_manager
        self.logger = logger
        self.console = Console()
        self.wrapper: Optional[ClientWrapper] = None
        
        # Cache for chats
        self._chats_cache: List[Tuple[int, str, str]] = []
    
    async def run(self):
        """Run the interactive TUI."""
        self._print_header()
        
        # Connect to Telegram
        if not await self._ensure_connected():
            return 1
        
        try:
            while True:
                action = self._main_menu()
                
                if action == 'quit':
                    break
                elif action == 'list':
                    await self._list_chats_interactive()
                elif action == 'forward':
                    await self._forward_interactive()
                elif action == 'delete':
                    await self._delete_interactive()
                elif action == 'status':
                    await self._show_status()
                elif action == 'logout':
                    await self._logout()
                    break
        
        finally:
            if self.wrapper:
                await self.wrapper.disconnect()
        
        return 0
    
    def _print_header(self):
        """Print the application header."""
        header = Panel(
            "[bold blue]Telegram CLI[/bold blue]\n"
            "[dim]Message forwarding automation tool[/dim]",
            style="blue",
            expand=False
        )
        self.console.print(header)
        self.console.print()
    
    async def _ensure_connected(self) -> bool:
        """Ensure we're connected and authenticated."""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True
        ) as progress:
            progress.add_task("Connecting to Telegram...", total=None)
            
            self.wrapper = ClientWrapper(self.config_manager, self.logger)
            
            try:
                is_authorized = await self.wrapper.connect()
                
                if not is_authorized:
                    self.console.print("[yellow]Not logged in. Please login first.[/yellow]")
                    self.console.print("Run: [bold]telegram-cli login[/bold]")
                    return False
                
                me = self.wrapper.me
                self.console.print(f"[green]✓[/green] Connected as [bold]{me.first_name}[/bold]")
                if me.username:
                    self.console.print(f"  Username: @{me.username}")
                self.console.print()
                return True
                
            except Exception as e:
                self.console.print(f"[red]Connection failed: {e}[/red]")
                return False
    
    def _main_menu(self) -> str:
        """Display main menu and get user choice."""
        self.console.print("\n[bold]What would you like to do?[/bold]\n")
        
        options = [
            ("1", "List chats", "list"),
            ("2", "Forward messages", "forward"),
            ("3", "Delete messages", "delete"),
            ("4", "View status", "status"),
            ("5", "Logout", "logout"),
            ("q", "Quit", "quit"),
        ]
        
        for key, label, _ in options:
            self.console.print(f"  [bold cyan]{key}[/bold cyan]  {label}")
        
        self.console.print()
        
        while True:
            choice = Prompt.ask("Select option", default="q")
            choice = choice.lower().strip()
            
            for key, _, action in options:
                if choice == key or choice == action:
                    return action
            
            self.console.print("[red]Invalid option. Try again.[/red]")
    
    async def _list_chats_interactive(self):
        """List chats with search and filtering."""
        self.console.print("\n[bold]List Chats[/bold]\n")
        
        # Get search term
        search = Prompt.ask("Search (leave empty for all)", default="")
        
        # Type filter
        type_filter = Prompt.ask(
            "Filter by type",
            choices=["all", "private", "group", "channel", "saved"],
            default="all"
        )
        if type_filter == "all":
            type_filter = None
        
        # Limit
        limit = IntPrompt.ask("Max results", default=20)
        
        # Fetch and display
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True
        ) as progress:
            progress.add_task("Fetching chats...", total=None)
            
            chats = []
            async for chat_id, title, chat_type in self.wrapper.list_chats():
                # Apply search filter
                if search and search.lower() not in title.lower():
                    continue
                
                # Apply type filter
                if type_filter and type_filter.lower() != chat_type.lower().strip():
                    continue
                
                chats.append((chat_id, title, chat_type))
                
                if len(chats) >= limit:
                    break
        
        # Display results
        if not chats:
            self.console.print("[yellow]No chats found matching your criteria.[/yellow]")
            return
        
        table = Table(title=f"Found {len(chats)} chats")
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Type", style="magenta", justify="center")
        table.add_column("Name", style="green")
        
        for chat_id, title, chat_type in chats:
            table.add_row(str(chat_id), chat_type, title)
        
        self.console.print(table)
        
        # Cache for later use
        self._chats_cache = chats
    
    async def _forward_interactive(self):
        """Interactive message forwarding."""
        self.console.print("\n[bold]Forward Messages[/bold]\n")
        
        # Get source
        source = Prompt.ask("Source chat ID (or 'list' to browse)")
        if source.lower() == 'list':
            await self._list_chats_interactive()
            source = Prompt.ask("Source chat ID")
        
        try:
            source_id = int(source)
        except ValueError:
            self.console.print("[red]Invalid chat ID[/red]")
            return
        
        # Get destination
        dest = Prompt.ask("Destination chat ID")
        try:
            dest_id = int(dest)
        except ValueError:
            self.console.print("[red]Invalid chat ID[/red]")
            return
        
        # Forward mode
        mode = Prompt.ask(
            "Mode",
            choices=["last", "all", "live"],
            default="last"
        )
        
        # Options
        drop_author = Confirm.ask("Remove 'Forwarded from' header?", default=False)
        delete_after = Confirm.ask("Delete from source after forwarding?", default=False)
        
        if mode == "last":
            count = IntPrompt.ask("Number of messages to forward", default=10)
            cmd = f"telegram-cli forward-last -s {source_id} -d {dest_id} --count {count}"
        elif mode == "all":
            cmd = f"telegram-cli forward-all -s {source_id} -d {dest_id}"
        else:
            cmd = f"telegram-cli forward-live -s {source_id} -d {dest_id}"
        
        if drop_author:
            cmd += " --drop-author"
        if delete_after:
            cmd += " --delete"
        
        self.console.print(f"\n[dim]Command:[/dim] [bold]{cmd}[/bold]\n")
        
        if Confirm.ask("Execute this command?", default=True):
            self.console.print("[yellow]Please run the command above in your terminal.[/yellow]")
            self.console.print("[dim]TUI execution coming in a future update.[/dim]")
    
    async def _delete_interactive(self):
        """Interactive message deletion."""
        self.console.print("\n[bold]Delete Messages[/bold]\n")
        
        # Get chat
        chat = Prompt.ask("Chat ID (or 'list' to browse)")
        if chat.lower() == 'list':
            await self._list_chats_interactive()
            chat = Prompt.ask("Chat ID")
        
        try:
            chat_id = int(chat)
        except ValueError:
            self.console.print("[red]Invalid chat ID[/red]")
            return
        
        # Delete mode
        mode = Prompt.ask(
            "Mode",
            choices=["last", "all"],
            default="last"
        )
        
        if mode == "last":
            count = IntPrompt.ask("Number of messages to delete", default=10)
            cmd = f"telegram-cli delete-last -c {chat_id} --count {count}"
        else:
            cmd = f"telegram-cli delete-all -c {chat_id}"
        
        self.console.print(f"\n[dim]Command:[/dim] [bold]{cmd}[/bold]\n")
        self.console.print("[red]⚠ Warning: Deletion cannot be undone![/red]\n")
        
        if Confirm.ask("Execute this command?", default=False):
            self.console.print("[yellow]Please run the command above in your terminal.[/yellow]")
    
    async def _show_status(self):
        """Show daemon and job status."""
        self.console.print("\n[bold]Status[/bold]\n")
        
        from .daemon import get_daemon_manager
        from .state import get_state_manager
        
        # Show running daemons
        daemon_manager = get_daemon_manager(self.config_manager.config_dir)
        daemons = daemon_manager.list_running()
        
        if daemons:
            table = Table(title="Running Daemons")
            table.add_column("PID", style="cyan")
            table.add_column("Command", style="green")
            table.add_column("Source", style="yellow")
            table.add_column("Running For", style="magenta")
            
            for d in daemons:
                table.add_row(
                    str(d.pid),
                    d.command,
                    str(d.source) if d.source else "-",
                    f"{int((d.running_for or 0) / 60)}m" if d.running_for else "-"
                )
            
            self.console.print(table)
        else:
            self.console.print("[dim]No daemons running[/dim]")
        
        self.console.print()
        
        # Show recent jobs
        state_manager = get_state_manager(self.config_manager.jobs_file)
        jobs = state_manager.get_recent_jobs(limit=5)
        
        if jobs:
            table = Table(title="Recent Jobs")
            table.add_column("Job ID", style="cyan")
            table.add_column("Type", style="green")
            table.add_column("Status", style="yellow")
            table.add_column("Progress", style="magenta")
            
            for job in jobs:
                status_style = {
                    'completed': 'green',
                    'failed': 'red',
                    'interrupted': 'yellow',
                    'running': 'blue',
                }.get(job.status.value, 'white')
                
                progress = f"{job.total_processed}/{job.total_messages or '?'}"
                table.add_row(
                    job.job_id[:8],
                    job.job_type.value,
                    f"[{status_style}]{job.status.value}[/{status_style}]",
                    progress
                )
            
            self.console.print(table)
        else:
            self.console.print("[dim]No recent jobs[/dim]")
    
    async def _logout(self):
        """Logout and clear session."""
        if Confirm.ask("Are you sure you want to logout?", default=False):
            if self.wrapper:
                await self.wrapper.logout()
            self.console.print("[green]✓[/green] Logged out successfully")


async def run_tui(config_manager: ConfigManager, logger: ForwarderLogger) -> int:
    """Run the TUI interface.
    
    Args:
        config_manager: Config manager
        logger: Logger
        
    Returns:
        Exit code
    """
    if not RICH_AVAILABLE:
        print("TUI requires the 'rich' library. Install it with:")
        print("  pip install rich")
        return 1
    
    tui = TUI(config_manager, logger)
    return await tui.run()
