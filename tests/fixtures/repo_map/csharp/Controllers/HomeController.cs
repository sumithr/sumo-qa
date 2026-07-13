using System;
using System.Collections.Generic;
using MyApp.Models;
using MyApp.Services;
using Newtonsoft.Json;

namespace MyApp.Controllers
{
    public class HomeController
    {
        private readonly OrderService _service = new OrderService();
        private readonly List<Order> _orders = new List<Order>();
    }
}
