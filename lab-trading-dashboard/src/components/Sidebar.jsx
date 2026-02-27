import React from "react";
import { FaChartBar, FaExchangeAlt, FaCog } from "react-icons/fa";
import { NavLink } from "react-router-dom";
import { Home, BarChart, Users, FileText, Menu, X, Plus, Space, Activity } from "lucide-react";

const SidebarItem = ({ icon: Icon, text, isOpen, to, isActive }) => (
  <NavLink
    to={to}
    className={({ isActive }) => 
      `flex items-center space-x-4 px-4 py-3 hover:bg-gray-700 rounded-lg cursor-pointer transition-all ${
        isActive ? 'bg-gray-700 text-blue-400' : 'text-white'
      }`
    }
  >
    <Icon size={24} />
    <span className={`transition-all ${isOpen ? "block" : "hidden"}`}>
      {text.replace(/_/g, " ")}
    </span>
  </NavLink>
);

const Sidebar = ({ isOpen, toggleSidebar }) => {
  return (
    <div className={`fixed h-screen bg-gradient-to-br from-gray-900 to-gray-800 text-white transition-all duration-300 ${isOpen ? "w-64" : "w-20"}`}>
      <div className="flex items-center justify-between p-5">
        <h2 className={`text-xl font-bold transition-all ${isOpen ? "block" : "hidden"}`}>LAB</h2>
        <button onClick={toggleSidebar} className="focus:outline-none">
          {isOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
      </div>
      <nav className="mt-10">
        <ul className="space-y-4">
          <li>
            <SidebarItem 
              icon={Home} 
              text="Dashboard" 
              isOpen={isOpen} 
              to="/"
            />
          </li>
          <li>
            <SidebarItem 
              icon={BarChart} 
              text="Trades" 
              isOpen={isOpen} 
              to="/trades"
            />
          </li>
          <li>
            <SidebarItem 
              icon={Users} 
              text="Clients" 
              isOpen={isOpen} 
              to="/clients"
            />
          </li>
          <li>
            <SidebarItem 
              icon={Activity} 
              text="Reports & Logs" 
              isOpen={isOpen} 
              to="/reports"
            />
          </li>
          <li>
            <SidebarItem 
              icon={Activity} 
              text="Binance Trade History" 
              isOpen={isOpen} 
              to="/income-history"
            />
          </li>
        </ul>
      </nav>
    </div>
  );
};

export default Sidebar;